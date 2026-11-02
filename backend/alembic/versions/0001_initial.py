"""Create the initial RepoAtlas PostgreSQL schema.

Revision ID: 0001_initial
"""
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

INITIAL_SQL = r"""
CREATE TABLE repositories (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider text NOT NULL DEFAULT 'github' CHECK (provider = 'github'),
  owner text NOT NULL,
  name text NOT NULL,
  canonical_url text NOT NULL UNIQUE,
  default_branch text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE analysis_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  repository_id uuid NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  commit_sha char(40) NOT NULL CHECK (commit_sha ~ '^[0-9a-f]{40}$'),
  status text NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued','fetching','parsing','resolving','completed','partial','failed')),
  progress int NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
  stats jsonb NOT NULL DEFAULT '{}'::jsonb,
  warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
  attempts int NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 2),
  error_code text,
  error_message text,
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  heartbeat_at timestamptz,
  finished_at timestamptz
);
CREATE INDEX ix_analysis_runs_repository_created ON analysis_runs(repository_id, created_at DESC);
CREATE INDEX ix_analysis_runs_worker ON analysis_runs(status, created_at) WHERE status = 'queued';
CREATE UNIQUE INDEX uq_analysis_sha_active_completed ON analysis_runs(repository_id, commit_sha)
  WHERE status IN ('queued','fetching','parsing','resolving','completed');

CREATE TABLE source_nodes (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
  parent_id bigint,
  kind text NOT NULL CHECK (kind IN ('directory','file')),
  name text NOT NULL,
  path text NOT NULL CHECK (path <> '' AND left(path, 1) <> '/'),
  language text,
  parse_status text NOT NULL DEFAULT 'not_applicable'
    CHECK (parse_status IN ('not_applicable','unsupported','parsed','failed','skipped')),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (run_id, path),
  UNIQUE (run_id, id),
  CONSTRAINT fk_source_nodes_parent_same_run FOREIGN KEY (run_id, parent_id)
    REFERENCES source_nodes(run_id, id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX ix_source_nodes_parent ON source_nodes(run_id, parent_id);
CREATE INDEX ix_source_nodes_kind ON source_nodes(run_id, kind);

CREATE TABLE code_symbols (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
  file_id bigint NOT NULL,
  parent_symbol_id bigint,
  kind text NOT NULL CHECK (kind IN ('function','class','method','interface')),
  name text NOT NULL,
  qualified_name text NOT NULL,
  start_line int NOT NULL CHECK (start_line > 0),
  end_line int NOT NULL CHECK (end_line >= start_line),
  UNIQUE (run_id, id),
  CONSTRAINT fk_symbol_file_same_run FOREIGN KEY (run_id, file_id)
    REFERENCES source_nodes(run_id, id) ON DELETE CASCADE,
  CONSTRAINT fk_symbol_parent_same_run FOREIGN KEY (run_id, parent_symbol_id)
    REFERENCES code_symbols(run_id, id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX ix_symbols_file_line ON code_symbols(run_id, file_id, start_line);
CREATE INDEX ix_symbols_name ON code_symbols(run_id, name);

CREATE TABLE code_references (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
  source_file_id bigint NOT NULL,
  target_file_id bigint,
  kind text NOT NULL DEFAULT 'imports' CHECK (kind = 'imports'),
  raw_ref text NOT NULL,
  source_line int NOT NULL CHECK (source_line > 0),
  resolution_status text NOT NULL CHECK (resolution_status IN ('resolved','unresolved','external')),
  CONSTRAINT ck_ref_target_matches_status CHECK (
    (resolution_status = 'resolved' AND target_file_id IS NOT NULL) OR
    (resolution_status <> 'resolved' AND target_file_id IS NULL)
  ),
  CONSTRAINT fk_ref_source_same_run FOREIGN KEY (run_id, source_file_id)
    REFERENCES source_nodes(run_id, id) ON DELETE CASCADE,
  CONSTRAINT fk_ref_target_same_run FOREIGN KEY (run_id, target_file_id)
    REFERENCES source_nodes(run_id, id) ON DELETE CASCADE
);
CREATE INDEX ix_refs_source ON code_references(run_id, source_file_id);
CREATE INDEX ix_refs_target ON code_references(run_id, target_file_id);

CREATE TABLE schema_tables (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
  schema_name text NOT NULL DEFAULT 'public',
  name text NOT NULL,
  source_file_id bigint,
  UNIQUE (run_id, schema_name, name),
  UNIQUE (run_id, id),
  CONSTRAINT fk_schema_table_source_same_run FOREIGN KEY (run_id, source_file_id)
    REFERENCES source_nodes(run_id, id) ON DELETE SET NULL (source_file_id)
);
CREATE INDEX ix_schema_tables_run ON schema_tables(run_id, name);

CREATE TABLE schema_columns (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
  table_id bigint NOT NULL,
  name text NOT NULL,
  data_type text NOT NULL,
  ordinal_position int NOT NULL CHECK (ordinal_position > 0),
  is_primary boolean NOT NULL DEFAULT false,
  is_nullable boolean NOT NULL DEFAULT true,
  UNIQUE (table_id, name),
  UNIQUE (run_id, id),
  CONSTRAINT fk_column_table_same_run FOREIGN KEY (run_id, table_id)
    REFERENCES schema_tables(run_id, id) ON DELETE CASCADE
);
CREATE INDEX ix_schema_columns_table ON schema_columns(run_id, table_id, ordinal_position);

CREATE TABLE schema_foreign_keys (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
  source_column_id bigint NOT NULL,
  target_column_id bigint,
  constraint_name text NOT NULL,
  ordinal_position int NOT NULL CHECK (ordinal_position > 0),
  target_ref text NOT NULL,
  CONSTRAINT fk_fk_source_same_run FOREIGN KEY (run_id, source_column_id)
    REFERENCES schema_columns(run_id, id) ON DELETE CASCADE,
  CONSTRAINT fk_fk_target_same_run FOREIGN KEY (run_id, target_column_id)
    REFERENCES schema_columns(run_id, id) ON DELETE SET NULL (target_column_id),
  UNIQUE (run_id, source_column_id, constraint_name, ordinal_position)
);
CREATE INDEX ix_fk_source ON schema_foreign_keys(run_id, source_column_id);
CREATE INDEX ix_fk_target ON schema_foreign_keys(run_id, target_column_id);

CREATE TABLE diagram_views (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
  diagram_type text NOT NULL
    CHECK (diagram_type IN ('directory','dependency','symbols','architecture','erd')),
  options_hash char(64) NOT NULL CHECK (options_hash ~ '^[0-9a-f]{64}$'),
  options jsonb NOT NULL,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, diagram_type, options_hash)
);
CREATE INDEX ix_diagram_views_run ON diagram_views(run_id, diagram_type);
"""


def upgrade():
    for statement in INITIAL_SQL.split(";"):
        if statement.strip():
            op.execute(statement.strip())


def downgrade():
    for table in (
        "diagram_views", "schema_foreign_keys", "schema_columns", "schema_tables",
        "code_references", "code_symbols", "source_nodes", "analysis_runs", "repositories",
    ):
        op.drop_table(table)
