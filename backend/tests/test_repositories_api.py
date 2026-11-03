"""GET /api/v1/repositories 테스트 (실제 DB 없이 가짜 세션으로 확인)."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from backend.app.api.deps import get_db
from backend.app.main import app


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def execute(self, stmt):
        self.statements.append(stmt)
        return FakeResult(self.rows)


def make_repo(owner, name):
    return SimpleNamespace(
        id=uuid4(), owner=owner, name=name, default_branch="main",
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def client_with(request):
    sessions = []

    def use(rows):
        session = FakeSession(rows)
        sessions.append(session)
        app.dependency_overrides[get_db] = lambda: session
        return TestClient(app), session

    yield use
    app.dependency_overrides.clear()


def test_healthz():
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_repositories_returns_api_spec_shape(client_with):
    repo = make_repo("example-org", "sample-web")
    run_id = uuid4()
    client, _ = client_with([(repo, run_id)])

    response = client.get("/api/v1/repositories")

    assert response.status_code == 200
    assert response.json() == {
        "items": [{
            "id": str(repo.id),
            "owner": "example-org",
            "name": "sample-web",
            "default_branch": "main",
            "latest_run_id": str(run_id),
        }],
        "next_cursor": None,
    }


def test_list_repositories_empty(client_with):
    client, _ = client_with([])
    response = client.get("/api/v1/repositories")
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_list_repositories_without_runs_has_null_latest_run(client_with):
    client, _ = client_with([(make_repo("a", "b"), None)])
    response = client.get("/api/v1/repositories")
    assert response.json()["items"][0]["latest_run_id"] is None


@pytest.mark.parametrize("limit", [0, 101])
def test_list_repositories_rejects_bad_limit(client_with, limit):
    client, _ = client_with([])
    response = client.get("/api/v1/repositories", params={"limit": limit})
    assert response.status_code == 422


def test_list_repositories_builds_postgres_query(client_with):
    client, session = client_with([])
    client.get("/api/v1/repositories", params={"limit": 5, "q": "sample"})

    sql = str(session.statements[0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
    ))
    assert "FROM repositories" in sql
    assert "ORDER BY repositories.created_at DESC, repositories.id DESC" in sql
    assert "LIMIT 5" in sql
    assert "ILIKE '%%sample%%'" in sql or "ILIKE '%sample%'" in sql
