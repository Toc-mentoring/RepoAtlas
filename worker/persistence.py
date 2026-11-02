"""Atomically persist one complete analysis snapshot and its terminal status."""

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.app.models import (
    AnalysisRun, CodeReference, CodeSymbol, Repository, SchemaColumn, SchemaForeignKey, SchemaTable, SourceNode,
)
from worker.jobs import JobClaim, LostLease


def persist_analysis(engine: Engine, claim: JobClaim, result: dict) -> None:
    if result.get("commit_sha") != claim.commit_sha or result.get("repository_url") != claim.repository_url:
        raise ValueError("Analysis result does not match its claimed repository and commit")
    if result.get("status") not in ("completed", "partial"):
        raise ValueError("Analysis result has an invalid terminal state")
    with Session(engine) as session, session.begin():
        run = session.scalar(select(AnalysisRun).where(AnalysisRun.id == claim.run_id).with_for_update())
        if run is None or run.attempts != claim.attempt or run.status != "resolving":
            raise LostLease(f"Analysis run {claim.run_id} is no longer owned by this worker")
        repo = session.get(Repository, run.repository_id)
        if run.commit_sha != claim.commit_sha or repo.canonical_url != claim.repository_url:
            raise ValueError("Claim no longer matches the database")
        if session.scalar(select(SourceNode.id).where(SourceNode.run_id == run.id).limit(1)) is not None:
            raise ValueError("Analysis run already has persisted source nodes")

        nodes = _save_nodes(session, run.id, result["source_nodes"])
        _save_symbols(session, run.id, result["code_symbols"], nodes)
        _save_references(session, run.id, result["code_references"], nodes)
        _save_schema(session, run.id, result["schema_tables"], nodes)
        run.stats = result["stats"]
        run.warnings = result["warnings"]
        run.status = result["status"]
        run.progress = 100
        run.finished_at = func.now()
        run.heartbeat_at = func.now()
        run.error_code = None
        run.error_message = None


def _save_nodes(session: Session, run_id, items: list[dict]) -> dict[str, SourceNode]:
    paths = [item["path"] for item in items]
    if len(set(paths)) != len(paths) or paths.count(".") != 1:
        raise ValueError("Analysis has duplicate paths or no unique root")
    by_path = {}
    pending = list(items)
    while pending:
        ready, waiting = [], []
        for item in pending:
            parent = item["parent_path"]
            (ready if parent is None or parent in by_path else waiting).append(item)
        if not ready:
            raise ValueError("Source nodes contain missing or cyclic parents")
        created = []
        for item in ready:
            parent_path = item["parent_path"]
            if (item["path"] == ".") != (parent_path is None):
                raise ValueError("Only the repository root may have no parent")
            parent = by_path.get(parent_path)
            if parent is not None and parent.kind != "directory":
                raise ValueError("A source node parent must be a directory")
            node = SourceNode(run_id=run_id, parent_id=parent.id if parent else None,
                              kind=item["kind"], name=item["name"], path=item["path"],
                              language=item["language"], parse_status=item["parse_status"], metadata_=item["metadata"])
            session.add(node)
            created.append((item["path"], node))
        session.flush()
        by_path.update(created)
        pending = waiting
    return by_path


def _file(nodes: dict[str, SourceNode], path: str) -> SourceNode:
    node = nodes.get(path)
    if node is None or node.kind != "file":
        raise ValueError("Analysis references a missing or non-file node")
    return node


def _symbol_key(item: dict) -> tuple:
    return item["file_path"], item["qualified_name"], item["start_line"], item["start_column"]


def _parent_key(item: dict) -> tuple | None:
    if item["parent_qualified_name"] is None:
        return None
    return item["file_path"], item["parent_qualified_name"], item["parent_start_line"], item["parent_start_column"]


def _save_symbols(session: Session, run_id, items: list[dict], nodes: dict[str, SourceNode]) -> None:
    keys = [_symbol_key(item) for item in items]
    if len(keys) != len(set(keys)):
        raise ValueError("Analysis has duplicate symbol identities")
    by_key = {}
    pending = list(items)
    while pending:
        ready, waiting = [], []
        for item in pending:
            parent = _parent_key(item)
            (ready if parent is None or parent in by_key else waiting).append(item)
        if not ready:
            raise ValueError("Symbols contain missing or cyclic parents")
        created = []
        for item in ready:
            parent = by_key.get(_parent_key(item))
            symbol = CodeSymbol(run_id=run_id, file_id=_file(nodes, item["file_path"]).id,
                                parent_symbol_id=parent.id if parent else None, kind=item["kind"], name=item["name"],
                                qualified_name=item["qualified_name"], start_line=item["start_line"], end_line=item["end_line"])
            session.add(symbol)
            created.append((_symbol_key(item), symbol))
        session.flush()
        by_key.update(created)
        pending = waiting


def _save_references(session: Session, run_id, items: list[dict], nodes: dict[str, SourceNode]) -> None:
    for item in items:
        status, target_path = item["resolution_status"], item["target_path"]
        if (status == "resolved") != (target_path is not None):
            raise ValueError("Import target does not match its resolution status")
        target_id = _file(nodes, target_path).id if target_path is not None else None
        session.add(CodeReference(run_id=run_id, source_file_id=_file(nodes, item["source_path"]).id,
                                  target_file_id=target_id, raw_ref=item["raw_ref"], source_line=item["source_line"],
                                  resolution_status=status))
    session.flush()


def _save_schema(session: Session, run_id, items: list[dict], nodes: dict[str, SourceNode]) -> None:
    tables = {}
    for item in items:
        key = item["schema_name"], item["name"]
        if key in tables:
            raise ValueError("Analysis has duplicate schema tables")
        table = SchemaTable(run_id=run_id, schema_name=key[0], name=key[1],
                            source_file_id=_file(nodes, item["source_path"]).id)
        session.add(table)
        tables[key] = table
    session.flush()
    columns = {}
    for item in items:
        table_key = item["schema_name"], item["name"]
        for column in item["columns"]:
            key = (*table_key, column["name"])
            if key in columns:
                raise ValueError("Analysis has duplicate schema columns")
            model = SchemaColumn(run_id=run_id, table_id=tables[table_key].id, **column)
            session.add(model)
            columns[key] = model
    session.flush()
    for item in items:
        for fk in item["foreign_keys"]:
            source_key = item["schema_name"], item["name"], fk["source_column"]
            if source_key not in columns:
                raise ValueError("Foreign key references a missing source column")
            target = columns.get((fk["target_schema"], fk["target_table"], fk["target_column"]))
            session.add(SchemaForeignKey(run_id=run_id, source_column_id=columns[source_key].id,
                                         target_column_id=target.id if target else None,
                                         constraint_name=fk["constraint_name"], ordinal_position=fk["ordinal_position"],
                                         target_ref=fk["target_ref"]))
    session.flush()
