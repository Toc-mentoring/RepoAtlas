import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models import AnalysisRun, CodeReference, Repository, SourceNode


@pytest.fixture
def migrated_database(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated PostgreSQL test database")
    admin = create_engine(url)
    schema = "test_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    schema_url = admin.url.update_query_dict({"options": f"-csearch_path={schema}"})
    monkeypatch.setenv("DATABASE_URL", schema_url.render_as_string(hide_password=False))
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(schema_url)
    try:
        yield engine, config
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_migration_roundtrip_and_model_agreement(migrated_database):
    engine, config = migrated_database
    expected = {
        "repositories", "analysis_runs", "source_nodes", "code_symbols", "code_references",
        "schema_tables", "schema_columns", "schema_foreign_keys", "diagram_views", "alembic_version",
    }
    assert set(inspect(engine).get_table_names()) == expected
    command.check(config)
    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    command.upgrade(config, "head")
    assert set(inspect(engine).get_table_names()) == expected


def test_snapshot_constraints(migrated_database):
    engine, _ = migrated_database
    with Session(engine) as session, session.begin():
        repo = Repository(owner="example", name="repo", canonical_url="https://github.com/example/repo", default_branch="main")
        session.add(repo)
        session.flush()
        run1 = AnalysisRun(repository_id=repo.id, commit_sha="a" * 40)
        run2 = AnalysisRun(repository_id=repo.id, commit_sha="b" * 40)
        session.add_all([run1, run2])
        session.flush()
        file1 = SourceNode(run_id=run1.id, kind="file", name="one.py", path="one.py")
        file2 = SourceNode(run_id=run2.id, kind="file", name="two.py", path="two.py")
        session.add_all([file1, file2])
        session.flush()
        ids = repo.id, run1.id, file1.id, file2.id

    repo_id, run1_id, file1_id, file2_id = ids
    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        session.add(AnalysisRun(repository_id=repo_id, commit_sha="a" * 40))
        session.flush()

    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        session.add(CodeReference(run_id=run1_id, source_file_id=file1_id, target_file_id=file2_id,
                                  raw_ref="two", source_line=1, resolution_status="resolved"))
        session.flush()

    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        session.add(CodeReference(run_id=run1_id, source_file_id=file1_id, target_file_id=file1_id,
                                  raw_ref="one", source_line=1, resolution_status="unresolved"))
        session.flush()
