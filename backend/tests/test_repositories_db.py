"""저장소 등록·목록·상세 API를 실제 PostgreSQL로 검사한다 (TEST_DATABASE_URL 필요)."""

from uuid import uuid4

from backend.app.services.github import GitHubRepository

URL = "https://github.com/example-org/sample-web"


def test_register_then_list_and_detail(api):
    created = api.client.post("/api/v1/repositories", json={"url": URL})
    assert created.status_code == 201
    body = created.json()
    assert body["provider"] == "github"
    assert body["owner"] == "example-org"
    assert body["name"] == "sample-web"
    assert body["canonical_url"] == URL
    assert body["default_branch"] == "main"
    assert body["is_existing"] is False

    listed = api.client.get("/api/v1/repositories").json()
    assert [item["id"] for item in listed["items"]] == [body["id"]]
    assert listed["items"][0]["latest_run_id"] is None

    detail = api.client.get(f"/api/v1/repositories/{body['id']}")
    assert detail.status_code == 200
    assert detail.json()["canonical_url"] == URL
    assert detail.json()["latest_run_id"] is None
    assert api.github.calls == 1


def test_register_same_repository_returns_existing_without_github(api):
    first = api.client.post("/api/v1/repositories", json={"url": URL}).json()

    again = api.client.post("/api/v1/repositories", json={"url": "https://github.com/Example-Org/sample-web.git/"})

    assert again.status_code == 200
    assert again.json()["id"] == first["id"]
    assert again.json()["is_existing"] is True
    assert api.github.calls == 1
    assert len(api.client.get("/api/v1/repositories").json()["items"]) == 1


def test_register_invalid_url_uses_error_format(api):
    response = api.client.post("/api/v1/repositories", json={"url": "https://gitlab.com/a/b"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_REPOSITORY_URL"
    assert error["request_id"].startswith("req-")
    assert api.github.calls == 0


def test_register_missing_github_repository(api):
    response = api.client.post("/api/v1/repositories", json={"url": "https://github.com/nobody/nothing"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"
    assert api.client.get("/api/v1/repositories").json()["items"] == []


def test_detail_not_found_and_bad_uuid(api):
    missing = api.client.get(f"/api/v1/repositories/{uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"

    assert api.client.get("/api/v1/repositories/not-a-uuid").status_code == 422


def test_list_repositories_pages_with_cursor(api):
    # 준비: 가짜 GitHub에 저장소 3개를 알려주고 전부 등록
    for name in ("repo-a", "repo-b", "repo-c"):
        api.github.repos[("example-org", name)] = GitHubRepository("example-org", name, "main")
        api.client.post("/api/v1/repositories", json={"url": f"https://github.com/example-org/{name}"})

    # 1페이지: 2개 + 책갈피 있음
    first = api.client.get("/api/v1/repositories?limit=2").json()
    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None

    # 2페이지: 책갈피로 이어서 → 1개 + 책갈피 없음(끝)
    second = api.client.get(f"/api/v1/repositories?limit=2&cursor={first['next_cursor']}").json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None

    # 두 페이지를 합치면 3개가 빠짐없이, 겹침없이
    names = {item["name"] for item in first["items"] + second["items"]}
    assert names == {"repo-a", "repo-b", "repo-c"}


def test_list_repositories_rejects_bad_cursor(api):
    response = api.client.get("/api/v1/repositories?cursor=!!!")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_FILTER"