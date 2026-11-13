"""Exercise the API and worker against the same migrated database."""

import zipfile

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db, get_github_client
from backend.app.main import app
from backend.app.services.github import GitHubRepository
from worker import main
from worker.analyzer import analyze_archive
from worker.archive import ArchiveLimits
from worker.github import parse_repository_url
from worker.jobs import claim_next


def test_api_queued_job_is_processed_and_returned_as_graphs(worker_db, tmp_path, monkeypatch):
    sha = "a" * 40
    url = "https://github.com/example/repo"
    path = tmp_path / "repo.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("repo-sha/src/main.py", "from . import helper\nimport missing\ndef run(): pass\n")
        archive.writestr("repo-sha/src/helper.py", "class Helper: pass\n")

    class FakeGitHub:
        def get_repository(self, ref):
            return GitHubRepository("example", "repo", "main")

        def get_branch_head_sha(self, ref, branch):
            return sha

    def get_test_db():
        with Session(worker_db) as session:
            yield session

    def analyze(url, commit, limits, *, on_progress, on_tick):
        on_progress("fetching", 5)
        return analyze_archive(path, parse_repository_url(url), commit, limits, progress=on_progress)

    monkeypatch.setattr(main, "run_analysis", analyze)
    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_github_client] = FakeGitHub
    try:
        with TestClient(app) as client:
            repo = client.post("/api/v1/repositories", json={"url": url})
            assert repo.status_code == 201
            queued = client.post(f"/api/v1/repositories/{repo.json()['id']}/analyses")
            assert queued.status_code == 202 and queued.json()["commit_sha"] == sha
            run_id = queued.json()["run_id"]
            assert main.process_claim(worker_db, claim_next(worker_db), ArchiveLimits())
            detail = client.get(f"/api/v1/analyses/{run_id}")
            assert detail.status_code == 200 and detail.json()["status"] == "partial"
            files = client.get(f"/api/v1/analyses/{run_id}/nodes").json()["items"]
            main_file = next(item for item in files if item["path"] == "src/main.py")
            for kind, options in (("directory", {}), ("dependency", {}),
                                  ("symbols", {"file_id": main_file["id"]})):
                response = client.post(f"/api/v1/analyses/{run_id}/diagrams", json={"type": kind, "options": options})
                assert response.status_code == 201
                graph = response.json()
                assert graph["nodes"] and graph["edges"]
                assert any(sha in node["data"].get("github_url", "") for node in graph["nodes"])
                if kind == "dependency":
                    assert len(graph["edges"]) == 1 and graph["unresolved_references"] == 1
    finally:
        app.dependency_overrides.clear()
