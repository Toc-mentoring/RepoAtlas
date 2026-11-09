"""저장소 등록·목록·상세 API를 실제 PostgreSQL로 검사한다.

TEST_DATABASE_URL이 없으면 건너뛴다.
"""

import os
from pathlib import Path
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


class FakeGitHub:
    """GitHub 대신 정해진 답을 주는 가짜. 몇 번 불렸는지 센다."""

    def __init__(self, repos=None):
        self.repos = repos or {}
        self.calls = 0

    def get_repository(self, ref):
        self.calls += 1
        key = (ref.owner.lower(), ref.name.lower())
        if key not in self.repos:
            raise ApiError(404, "REPOSITORY_NOT_FOUND", "not found")
        return self.repos[key]


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

    github = FakeGitHub({
        ("example-org", "sample-web"): GitHubRepository("example-org", "sample-web", "main"),
    })

    def override_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_github_client] = lambda: github
    try:
        yield TestClient(app), github
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_register_then_list_and_detail(api):
    client, github = api

    created = client.post("/api/v1/repositories", json={"url": "https://github.com/example-org/sample-web"})
    assert created.status_code == 201
    body = created.json()
    assert body["provider"] == "github"
    assert body["owner"] == "example-org"
    assert body["name"] == "sample-web"
    assert body["canonical_url"] == "https://github.com/example-org/sample-web"
    assert body["default_branch"] == "main"
    assert body["is_existing"] is False

    listed = client.get("/api/v1/repositories").json()
    assert [item["id"] for item in listed["items"]] == [body["id"]]
    assert listed["items"][0]["latest_run_id"] is None

    detail = client.get(f"/api/v1/repositories/{body['id']}")
    assert detail.status_code == 200
    assert detail.json()["canonical_url"] == body["canonical_url"]
    assert detail.json()["latest_run_id"] is None
    assert github.calls == 1


def test_register_same_repository_returns_existing_without_github(api):
    client, github = api
    first = client.post("/api/v1/repositories", json={"url": "https://github.com/example-org/sample-web"}).json()

    again = client.post("/api/v1/repositories", json={"url": "https://github.com/Example-Org/sample-web.git/"})

    assert again.status_code == 200
    assert again.json()["id"] == first["id"]
    assert again.json()["is_existing"] is True
    assert github.calls == 1
    assert len(client.get("/api/v1/repositories").json()["items"]) == 1


def test_register_invalid_url_uses_error_format(api):
    client, github = api
    response = client.post("/api/v1/repositories", json={"url": "https://gitlab.com/a/b"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_REPOSITORY_URL"
    assert error["request_id"].startswith("req-")
    assert github.calls == 0


def test_register_missing_github_repository(api):
    client, _ = api
    response = client.post("/api/v1/repositories", json={"url": "https://github.com/nobody/nothing"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"
    assert client.get("/api/v1/repositories").json()["items"] == []


def test_detail_not_found_and_bad_uuid(api):
    client, _ = api
    missing = client.get(f"/api/v1/repositories/{uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"

    assert client.get("/api/v1/repositories/not-a-uuid").status_code == 422
