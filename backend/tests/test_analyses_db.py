"""분석 요청·이력·상태 API를 실제 PostgreSQL로 검사한다 (TEST_DATABASE_URL 필요)."""

from uuid import uuid4

from sqlalchemy import text

HEAD_SHA = "0123456789abcdef0123456789abcdef01234567"


def register(api):
    return api.client.post("/api/v1/repositories", json={"url": "https://github.com/example-org/sample-web"}).json()


def set_status(api, run_id, status):
    with api.engine.begin() as connection:
        connection.execute(text("UPDATE analysis_runs SET status = :s WHERE id = :id"), {"s": status, "id": run_id})


def test_request_analysis_creates_queued_run(api):
    repo = register(api)

    response = api.client.post(f"/api/v1/repositories/{repo['id']}/analyses")

    assert response.status_code == 202
    body = response.json()
    assert body["repository_id"] == repo["id"]
    assert body["commit_sha"] == HEAD_SHA
    assert body["status"] == "queued"
    assert body["reused"] is False
    assert body["status_url"] == f"/api/v1/analyses/{body['run_id']}"

    status = api.client.get(body["status_url"])
    assert status.status_code == 200
    detail = status.json()
    assert detail["id"] == body["run_id"]
    assert detail["status"] == "queued"
    assert detail["progress"] == 0
    assert detail["stats"] == {}
    assert detail["warnings"] == []
    assert detail["finished_at"] is None

    listed = api.client.get("/api/v1/repositories").json()["items"][0]
    assert listed["latest_run_id"] == body["run_id"]


def test_same_sha_in_progress_or_completed_is_reused(api):
    repo = register(api)
    first = api.client.post(f"/api/v1/repositories/{repo['id']}/analyses").json()

    again = api.client.post(f"/api/v1/repositories/{repo['id']}/analyses")
    assert again.status_code == 200
    assert again.json()["run_id"] == first["run_id"]
    assert again.json()["reused"] is True

    set_status(api, first["run_id"], "completed")
    completed = api.client.post(f"/api/v1/repositories/{repo['id']}/analyses")
    assert completed.status_code == 200
    assert completed.json()["run_id"] == first["run_id"]


def test_failed_run_can_be_retried_with_new_run(api):
    repo = register(api)
    first = api.client.post(f"/api/v1/repositories/{repo['id']}/analyses").json()
    set_status(api, first["run_id"], "failed")

    retry = api.client.post(f"/api/v1/repositories/{repo['id']}/analyses")

    assert retry.status_code == 202
    assert retry.json()["run_id"] != first["run_id"]
    history = api.client.get(f"/api/v1/repositories/{repo['id']}/analyses").json()["items"]
    assert [item["id"] for item in history] == [retry.json()["run_id"], first["run_id"]]
    assert history[1]["status"] == "failed"


def test_new_commit_creates_new_run(api):
    repo = register(api)
    first = api.client.post(f"/api/v1/repositories/{repo['id']}/analyses").json()
    api.github.head_sha = "f" * 40

    second = api.client.post(f"/api/v1/repositories/{repo['id']}/analyses")

    assert second.status_code == 202
    assert second.json()["commit_sha"] == "f" * 40
    assert second.json()["run_id"] != first["run_id"]


def test_not_found_errors(api):
    missing_repo = api.client.post(f"/api/v1/repositories/{uuid4()}/analyses")
    assert missing_repo.status_code == 404
    assert missing_repo.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"

    missing_history = api.client.get(f"/api/v1/repositories/{uuid4()}/analyses")
    assert missing_history.status_code == 404

    missing_run = api.client.get(f"/api/v1/analyses/{uuid4()}")
    assert missing_run.status_code == 404
    assert missing_run.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"
