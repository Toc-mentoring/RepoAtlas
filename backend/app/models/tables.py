"""Database tables for immutable repository analysis snapshots."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger, Boolean, CHAR, CheckConstraint, DateTime, ForeignKey,
    ForeignKeyConstraint, Identity, Index, Integer, Text,
    UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (CheckConstraint("provider = 'github'", name="ck_repositories_provider"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    provider: Mapped[str] = mapped_column(Text, server_default=text("'github'"))
    owner: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text, unique=True)
    default_branch: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint("commit_sha ~ '^[0-9a-f]{40}$'", name="ck_analysis_runs_sha"),
        CheckConstraint("status IN ('queued','fetching','parsing','resolving','completed','partial','failed')", name="ck_analysis_runs_status"),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_analysis_runs_progress"),
        CheckConstraint("attempts BETWEEN 0 AND 2", name="ck_analysis_runs_attempts"),
        Index("ix_analysis_runs_repository_created", "repository_id", text("created_at DESC")),
        Index("ix_analysis_runs_worker", "status", "created_at", postgresql_where=text("status = 'queued'")),
        Index("uq_analysis_sha_active_completed", "repository_id", "commit_sha", unique=True,
              postgresql_where=text("status IN ('queued','fetching','parsing','resolving','completed')")),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    repository_id: Mapped[UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    commit_sha: Mapped[str] = mapped_column(CHAR(40))
    status: Mapped[str] = mapped_column(Text, server_default=text("'queued'"))
    progress: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    stats: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    warnings: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceNode(Base):
    __tablename__ = "source_nodes"
    __table_args__ = (
        CheckConstraint("kind IN ('directory','file')", name="ck_source_nodes_kind"),
        CheckConstraint("path <> '' AND left(path, 1) <> '/'", name="ck_source_nodes_path"),
        CheckConstraint("parse_status IN ('not_applicable','unsupported','parsed','failed','skipped')", name="ck_source_nodes_parse_status"),
        UniqueConstraint("run_id", "path"), UniqueConstraint("run_id", "id"),
        ForeignKeyConstraint(["run_id", "parent_id"], ["source_nodes.run_id", "source_nodes.id"],
                             name="fk_source_nodes_parent_same_run", ondelete="CASCADE", deferrable=True, initially="DEFERRED"),
        Index("ix_source_nodes_parent", "run_id", "parent_id"),
        Index("ix_source_nodes_kind", "run_id", "kind"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    parent_id: Mapped[int | None] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(Text, server_default=text("'not_applicable'"))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))


class CodeSymbol(Base):
    __tablename__ = "code_symbols"
    __table_args__ = (
        CheckConstraint("kind IN ('function','class','method','interface')", name="ck_code_symbols_kind"),
        CheckConstraint("start_line > 0", name="ck_code_symbols_start"),
        CheckConstraint("end_line >= start_line", name="ck_code_symbols_end"),
        UniqueConstraint("run_id", "id"),
        ForeignKeyConstraint(["run_id", "file_id"], ["source_nodes.run_id", "source_nodes.id"], name="fk_symbol_file_same_run", ondelete="CASCADE"),
        ForeignKeyConstraint(["run_id", "parent_symbol_id"], ["code_symbols.run_id", "code_symbols.id"],
                             name="fk_symbol_parent_same_run", ondelete="CASCADE", deferrable=True, initially="DEFERRED"),
        Index("ix_symbols_file_line", "run_id", "file_id", "start_line"),
        Index("ix_symbols_name", "run_id", "name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    file_id: Mapped[int] = mapped_column(BigInteger)
    parent_symbol_id: Mapped[int | None] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    qualified_name: Mapped[str] = mapped_column(Text)
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)


class CodeReference(Base):
    __tablename__ = "code_references"
    __table_args__ = (
        CheckConstraint("kind = 'imports'", name="ck_code_references_kind"),
        CheckConstraint("source_line > 0", name="ck_code_references_line"),
        CheckConstraint("resolution_status IN ('resolved','unresolved','external')", name="ck_code_references_status"),
        CheckConstraint("(resolution_status = 'resolved' AND target_file_id IS NOT NULL) OR (resolution_status <> 'resolved' AND target_file_id IS NULL)", name="ck_ref_target_matches_status"),
        ForeignKeyConstraint(["run_id", "source_file_id"], ["source_nodes.run_id", "source_nodes.id"], name="fk_ref_source_same_run", ondelete="CASCADE"),
        ForeignKeyConstraint(["run_id", "target_file_id"], ["source_nodes.run_id", "source_nodes.id"], name="fk_ref_target_same_run", ondelete="CASCADE"),
        Index("ix_refs_source", "run_id", "source_file_id"), Index("ix_refs_target", "run_id", "target_file_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    source_file_id: Mapped[int] = mapped_column(BigInteger)
    target_file_id: Mapped[int | None] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(Text, server_default=text("'imports'"))
    raw_ref: Mapped[str] = mapped_column(Text)
    source_line: Mapped[int] = mapped_column(Integer)
    resolution_status: Mapped[str] = mapped_column(Text)


class SchemaTable(Base):
    __tablename__ = "schema_tables"
    __table_args__ = (
        UniqueConstraint("run_id", "schema_name", "name"), UniqueConstraint("run_id", "id"),
        ForeignKeyConstraint(["run_id", "source_file_id"], ["source_nodes.run_id", "source_nodes.id"],
                             name="fk_schema_table_source_same_run", ondelete="SET NULL (source_file_id)"),
        Index("ix_schema_tables_run", "run_id", "name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    schema_name: Mapped[str] = mapped_column(Text, server_default=text("'public'"))
    name: Mapped[str] = mapped_column(Text)
    source_file_id: Mapped[int | None] = mapped_column(BigInteger)


class SchemaColumn(Base):
    __tablename__ = "schema_columns"
    __table_args__ = (
        CheckConstraint("ordinal_position > 0", name="ck_schema_columns_ordinal"),
        UniqueConstraint("table_id", "name"), UniqueConstraint("run_id", "id"),
        ForeignKeyConstraint(["run_id", "table_id"], ["schema_tables.run_id", "schema_tables.id"], name="fk_column_table_same_run", ondelete="CASCADE"),
        Index("ix_schema_columns_table", "run_id", "table_id", "ordinal_position"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    table_id: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(Text)
    data_type: Mapped[str] = mapped_column(Text)
    ordinal_position: Mapped[int] = mapped_column(Integer)
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_nullable: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class SchemaForeignKey(Base):
    __tablename__ = "schema_foreign_keys"
    __table_args__ = (
        CheckConstraint("ordinal_position > 0", name="ck_schema_fk_ordinal"),
        ForeignKeyConstraint(["run_id", "source_column_id"], ["schema_columns.run_id", "schema_columns.id"], name="fk_fk_source_same_run", ondelete="CASCADE"),
        ForeignKeyConstraint(["run_id", "target_column_id"], ["schema_columns.run_id", "schema_columns.id"],
                             name="fk_fk_target_same_run", ondelete="SET NULL (target_column_id)"),
        UniqueConstraint("run_id", "source_column_id", "constraint_name", "ordinal_position"),
        Index("ix_fk_source", "run_id", "source_column_id"), Index("ix_fk_target", "run_id", "target_column_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    source_column_id: Mapped[int] = mapped_column(BigInteger)
    target_column_id: Mapped[int | None] = mapped_column(BigInteger)
    constraint_name: Mapped[str] = mapped_column(Text)
    ordinal_position: Mapped[int] = mapped_column(Integer)
    target_ref: Mapped[str] = mapped_column(Text)


class DiagramView(Base):
    __tablename__ = "diagram_views"
    __table_args__ = (
        CheckConstraint("diagram_type IN ('directory','dependency','symbols','architecture','erd')", name="ck_diagram_views_type"),
        CheckConstraint("options_hash ~ '^[0-9a-f]{64}$'", name="ck_diagram_views_hash"),
        UniqueConstraint("run_id", "diagram_type", "options_hash"),
        Index("ix_diagram_views_run", "run_id", "diagram_type"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    run_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    diagram_type: Mapped[str] = mapped_column(Text)
    options_hash: Mapped[str] = mapped_column(CHAR(64))
    options: Mapped[dict] = mapped_column(JSONB)
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
