import copy
import json
import zipfile
from dataclasses import asdict

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models import AnalysisRun, CodeReference, CodeSymbol, Repository, SchemaColumn, SchemaForeignKey, SchemaTable, SourceNode
from worker.analyzer import analyze_archive
from worker.archive import ArchiveLimits
from worker.github import parse_repository_url
from worker.jobs import LostLease, claim_next, update_progress
from worker.parsers.javascript_ts import parse_javascript
from worker.persistence import persist_analysis


def prepare(engine, tmp_path):
    with Session(engine) as session, session.begin():
        repo = Repository(owner="example", name="repo", canonical_url="https://github.com/example/repo", default_branch="main")
        session.add(repo)
        session.flush()
        session.add(AnalysisRun(repository_id=repo.id, commit_sha="a" * 40))
    claim = claim_next(engine)
    update_progress(engine, claim, "parsing", 30)
    update_progress(engine, claim, "resolving", 75)
    archive_path = tmp_path / "repo.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("repo-sha/src/main.py", "from . import helper\nclass Service:\n    def run(self): pass\nsecret = 'never-store-this'\n")
        archive.writestr("repo-sha/src/helper.py", "def helper(): pass\n")
        archive.writestr("repo-sha/schema.sql", "CREATE TABLE users(id BIGINT PRIMARY KEY); CREATE TABLE posts(id BIGINT, user_id BIGINT REFERENCES users(id));")
    result = analyze_archive(archive_path, parse_repository_url(claim.repository_url), claim.commit_sha, ArchiveLimits())
    return claim, result


def test_persists_complete_snapshot_and_terminal_state(worker_db, tmp_path):
    claim, result = prepare(worker_db, tmp_path)
    persist_analysis(worker_db, claim, result)
    with Session(worker_db) as session:
        run = session.get(AnalysisRun, claim.run_id)
        assert (run.status, run.progress, run.stats["file_count"]) == ("completed", 100, 3)
        nodes = session.scalars(select(SourceNode).where(SourceNode.run_id == run.id)).all()
        symbols = session.scalars(select(CodeSymbol).where(CodeSymbol.run_id == run.id)).all()
        refs = session.scalars(select(CodeReference).where(CodeReference.run_id == run.id)).all()
        tables = session.scalars(select(SchemaTable).where(SchemaTable.run_id == run.id)).all()
        columns = session.scalars(select(SchemaColumn).where(SchemaColumn.run_id == run.id)).all()
        foreign_keys = session.scalars(select(SchemaForeignKey).where(SchemaForeignKey.run_id == run.id)).all()
        by_path = {node.path: node for node in nodes}
        assert by_path["src/main.py"].parent_id == by_path["src"].id
        assert {(s.qualified_name, s.kind) for s in symbols} == {("Service", "class"), ("helper", "function"), ("Service.run", "method")}
        assert next(s for s in symbols if s.qualified_name == "Service.run").parent_symbol_id == next(s.id for s in symbols if s.name == "Service")
        assert len(refs) == 1 and refs[0].source_file_id == by_path["src/main.py"].id and refs[0].target_file_id == by_path["src/helper.py"].id
        assert len(tables) == 2 and len(columns) == 3
        assert len(foreign_keys) == 1 and foreign_keys[0].target_column_id is not None
        assert "never-store-this" not in json.dumps([node.metadata_ for node in nodes])
    with pytest.raises(LostLease):
        persist_analysis(worker_db, claim, result)


def test_invalid_snapshot_rolls_back_every_row(worker_db, tmp_path):
    claim, result = prepare(worker_db, tmp_path)
    invalid = copy.deepcopy(result)
    invalid["code_references"][0]["target_path"] = "missing.py"
    with pytest.raises(ValueError, match="missing or non-file"):
        persist_analysis(worker_db, claim, invalid)
    with Session(worker_db) as session:
        assert session.scalar(select(func.count()).select_from(SourceNode)) == 0
        assert session.scalar(select(func.count()).select_from(CodeSymbol)) == 0
        assert session.get(AnalysisRun, claim.run_id).status == "resolving"


def test_same_line_symbol_parents_and_unresolved_foreign_keys(worker_db, tmp_path):
    claim, result = prepare(worker_db, tmp_path)
    result["source_nodes"].append({"path": "same.js", "parent_path": ".", "name": "same.js", "kind": "file",
                                   "language": "javascript", "parse_status": "parsed", "metadata": {}})
    symbols, _, _ = parse_javascript("same.js", b"button.onclick = () => { function f(){function g(){}} function f(){function g(){}} }")
    result["code_symbols"].extend(asdict(symbol) for symbol in symbols)
    result["stats"]["file_count"] += 1
    result["stats"]["symbols"] += len(symbols)
    posts = next(table for table in result["schema_tables"] if table["name"] == "posts")
    posts["foreign_keys"].append({"source_column": "user_id", "constraint_name": "fk_missing", "ordinal_position": 1,
                                  "target_schema": "public", "target_table": "missing", "target_column": "id",
                                  "target_ref": "public.missing(id)"})
    result["warnings"].append("Unresolved foreign key")
    result["status"] = "partial"
    persist_analysis(worker_db, claim, result)
    with Session(worker_db) as session:
        same_id = session.scalar(select(SourceNode.id).where(SourceNode.run_id == claim.run_id, SourceNode.path == "same.js"))
        saved = session.scalars(select(CodeSymbol).where(CodeSymbol.file_id == same_id).order_by(CodeSymbol.id)).all()
        parents = [item for item in saved if item.name == "f"]
        children = [item for item in saved if item.name == "g"]
        callback = next(item for item in saved if item.name.startswith("<anonymous@"))
        assert [parent.parent_symbol_id for parent in parents] == [callback.id, callback.id]
        assert [child.parent_symbol_id for child in children] == [parent.id for parent in parents]
        missing = session.scalar(select(SchemaForeignKey).where(SchemaForeignKey.constraint_name == "fk_missing"))
        assert missing.target_column_id is None and missing.target_ref == "public.missing(id)"
