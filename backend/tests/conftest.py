"""API를 실제 PostgreSQL로 검사할 때 쓰는 공통 준비물.

TEST_DATABASE_URL이 없으면 이 준비물을 쓰는 테스트는 건너뛴다.
"""

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db, get_github_client
from backend.app.api.errors import ApiError
from backend.app.main import app
from backend.app.services.github import GitHubRepository

HEAD_SHA = "0123456789abcdef0123456789abcdef01234567"


class FakeGitHub:
    """GitHub 대신 정해진 답을 주는 가짜. 몇 번 불렸는지 센다."""

    def __init__(self):
        self.repos = {("example-org", "sample-web"): GitHubRepository("example-org", "sample-web", "main")}
        self.head_sha = HEAD_SHA
        self.calls = 0

    def get_repository(self, ref):
        self.calls += 1
        key = (ref.owner.lower(), ref.name.lower())
        if key not in self.repos:
            raise ApiError(404, "REPOSITORY_NOT_FOUND", "not found")
        return self.repos[key]

    def get_branch_head_sha(self, ref, branch):
        self.calls += 1
        return self.head_sha


@pytest.fixture
def api(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated PostgreSQL test database")
    admin = create_engine(url)
    schema = "test_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    schema_url = admin.url.update_query_dict({"options": f"-csearch_path={schema}"})
    monkeypatch.setenv("DATABASE_URL", schema_url.render_as_string(hide_password=False))
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    engine = create_engine(schema_url)
    github = FakeGitHub()

    def override_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_github_client] = lambda: github
    try:
        yield SimpleNamespace(client=TestClient(app), github=github, engine=engine)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
