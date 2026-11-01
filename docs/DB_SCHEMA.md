# PostgreSQL 데이터베이스 설계 (DB_SCHEMA)

[← README](../README.md) · [ERD](ERD.md) · [API](API_SPEC.md) · [분석 규격](CODE_ANALYSIS.md)

## 1. 설계 목표

**총 9개 테이블.** `repositories`의 메타데이터와 `analysis_runs`의 불변 커밋별 분석 스냅샷을 분리하고, 외부 코드 원문 대신 **경로·심볼·참조·DDL 메타데이터**만 보관합니다. 동일 SHA의 성공 결과를 캐시하고 선택한 다이어그램을 `diagram_views`로 저장합니다.

PostgreSQL **16 이상**을 로컬/배포의 기준 버전으로 정합니다. 모든 실행은 `Alembic` migration으로 적용하며, 아래 SQL은 모델 구현의 규범 예시입니다(실제 DB 실행 테스트는 개발 시작 후 수행).

## 2. 데이터 모델 및 NULL 규칙

| 테이블 | 필수 관계·컬럼 요약 | NULL 허용 컬럼 | UNIQUE / 주요 CHECK |
|---|---|---|---|
| `repositories` | id UUID PK, provider, owner, name, canonical_url, default_branch, created_at | 없음 | canonical_url UNIQUE, provider='github' |
| `analysis_runs` | id UUID PK, repository_id FK, commit_sha CHAR(40), status, progress, stats JSONB, warnings JSONB, attempts, created_at | started_at, heartbeat_at, finished_at, error_code, error_message | status ENUM 유사 CHECK; 진행/완료 동일 SHA 중복 방지 partial unique index |
| `source_nodes` | id BIGINT PK, run_id FK, kind, name, path, parse_status, metadata JSONB | parent_id, language | UNIQUE(run_id,path); kind directory/file |
| `code_symbols` | id BIGINT PK, run_id FK, file_id FK, kind, name, qualified_name, start_line, end_line | parent_symbol_id | line>0, end>=start |
| `code_references` | id BIGINT PK, run_id FK, source_file_id FK, raw_ref, kind, source_line, resolution_status | target_file_id | resolved만 target NOT NULL |
| `schema_tables` | id BIGINT PK, run_id FK, schema_name, name | source_file_id | UNIQUE(run_id,schema_name,name) |
| `schema_columns` | id BIGINT PK, run_id FK, table_id FK, name, data_type, ordinal_position, is_primary, is_nullable | 없음 | UNIQUE(table_id,name) |
| `schema_foreign_keys` | id BIGINT PK, run_id FK, source_column_id FK, constraint_name, ordinal_position, target_ref | target_column_id | composite FK 컬럼별 한 행 |
| `diagram_views` | id UUID PK, run_id FK, diagram_type, options_hash, options JSONB, payload JSONB | 없음 | UNIQUE(run_id,diagram_type,options_hash) |

## 3. DDL (PostgreSQL 16+)

```sql
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
```

### 관계형 제약 추가 확인

- 복합 FK로 `source_nodes`, `code_symbols`, `code_references`, `schema_*`의 **다른 run 간 참조를 방지**합니다.
- 복합 FK가 target id만 확인하고 target 행의 `kind='file'`까지 확인하지는 않으므로 **서비스 계층에서 file_id가 실제 파일인지 검증**하고 테스트합니다.
- `schema_foreign_keys.target_ref`는 원본 참조 대상 문자열입니다. 해결되지 않은 FK는 `target_column_id=NULL`, `target_ref`는 남깁니다.
- 같은 시점의 여러 SQL 파일에 동일 테이블이 선언되면 무조건 합치지 않고 충돌 경고를 남깁니다.
- `source_nodes.metadata`의 `config_facts`는 비밀번호/원본 설정 값이 아닌 허용 필드만 적재합니다.

## 4. 핵심 쓰기 트랜잭션

**분석 실행 생성:**
1. GitHub API에서 최신 SHA 확인.
2. repo_id+sha의 진행 중/완료 run 조회.
3. 있으면 기존 반환. 없으면 queued INSERT (unique 충돌 시 재조회).

**Worker:**
1. 아래 구문으로 큐에서 한 건 점유(짧은 트랜잭션).
2. 가져온 `run_id`의 상태를 fetching으로 바꾸고 즉시 커밋.
3. 소스 수집 및 파싱은 파일 시스템 임시 영역에서 실시하며 DB 트랜잭션을 길게 유지하지 않음.
4. 분석 결과를 부모→자식 순으로 한 트랜잭션에 INSERT하고 `completed`/`partial`로 종료. DB 오류 시 롤백, 작업 실패 상태 별도 저장.

```sql
WITH picked AS (
  SELECT id FROM analysis_runs
  WHERE status = 'queued'
  ORDER BY created_at
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
UPDATE analysis_runs r
SET status = 'fetching', started_at = now(), heartbeat_at = now(),
    attempts = attempts + 1
FROM picked
WHERE r.id = picked.id
RETURNING r.*;
```

시스템 중단 시 `fetching/parsing/resolving`에서 heartbeat이 오래된 run을 재실행하려면 상태를 queued로 되돌리고 부분 데이터가 없는지 확인한 후 재시도합니다. `attempts`가 2에 도달하면 failed. 분석 단계의 중간 임시 결과는 DB에 쓰지 않는 정책으로 복구를 단순화합니다.

## 5. 조회/성능 인덱스 계획

- 폴더 트리: `source_nodes(run_id,parent_id)` 및 `UNIQUE(run_id,path)`.
- 심볼: `code_symbols(run_id,file_id,start_line)`, 이름 검색은 MVP에서는 LIMIT + `ILIKE`.
- 의존성: `code_references(run_id,source_file_id/target_file_id)`.
- 최근 분석/큐: `analysis_runs(repository_id, created_at DESC)`와 상태 기반 부분 인덱스.
- 다이어그램 캐시: `UNIQUE(run_id,diagram_type,options_hash)`.

대규모 검색이 필요해지면 `pg_trgm` 인덱스, 그래프 질의 최적화, 더 세밀한 데이터 분할을 후속으로 추가합니다.

## 6. 보존·삭제·재사용

- 저장소별 **최근 완료 스냅샷 3개** 보존, 최소 1개 성공 스냅샷은 유지. 실패 실행은 최근 7일 로그만 유지(운영 정책 초기값).
- 임시 ZIP/추출 파일은 종료 후 즉시 삭제하고 DB에 소스 전문을 저장하지 않음.
- 삭제된 `analysis_runs`에 연결된 7개 하위 메타데이터/캐시 테이블은 `ON DELETE CASCADE`로 자동 정리(실제 FK 경로에 따름).
- 같은 SHA의 완료 결과는 API에서 재사용. 새로운 SHA는 새 run을 생성하며 이전 DB 결과를 덮어쓰지 않음.
- 다이어그램 캐시는 `run_id + type + canonical JSON 옵션 hash + analyzer schema version`에 따라 다른 key를 생성. 파서 정책 변경 시 새 분석 run 또는 캐시 키 버전 변경.
