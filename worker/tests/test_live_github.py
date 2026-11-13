"""Opt-in end-to-end checks using a public, pinned GitHub commit."""

import json
import os
import subprocess
import sys

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models import AnalysisRun, CodeReference, CodeSymbol, Repository, SourceNode

pytestmark = pytest.mark.skipif(os.environ.get("REPOATLAS_LIVE_TESTS") != "1", reason="Set REPOATLAS_LIVE_TESTS=1 for GitHub integration")
URL = "https://github.com/psf/requests"
SHA = "3c7baaa05ab4aa49cc819ce3a819d260de19c157"
PUBLIC_FIXTURES = [
    (URL, SHA),
    ("https://github.com/pallets/flask", "49943b5a94413a530761350f04e896f76e8d620e"),
    ("https://github.com/expressjs/express", "43fca52d28a422c8be48fd489cbd4f2d6152bab6"),
]


@pytest.mark.parametrize("url,sha", PUBLIC_FIXTURES)
def test_real_github_url_generates_json_without_database(tmp_path, url, sha):
    output = tmp_path / "analysis.json"
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    completed = subprocess.run([sys.executable, "-m", "worker.cli", url, "--sha", sha, "--output", str(output)],
                               env=env, capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["commit_sha"] == sha and result["status"] in ("completed", "partial")
    assert result["stats"]["file_count"] > 0 and result["stats"]["symbols"] > 0
    assert result["stats"]["resolved_imports"] > 0
    if url == URL:
        assert result["stats"]["file_count"] > 100 and result["stats"]["symbols"] > 100


@pytest.mark.parametrize("url,sha", PUBLIC_FIXTURES)
def test_registered_job_fetches_github_and_persists_results(worker_db, url, sha):
    owner, name = url.rsplit("/", 2)[-2:]
    with Session(worker_db) as session, session.begin():
        repo = Repository(owner=owner, name=name, canonical_url=url, default_branch="main")
        session.add(repo)
        session.flush()
        run = AnalysisRun(repository_id=repo.id, commit_sha=sha)
        session.add(run)
        session.flush()
        run_id = run.id
    completed = subprocess.run([sys.executable, "-m", "worker.main", "--once"],
                               env=os.environ.copy(), capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stderr
    with Session(worker_db) as session:
        run = session.get(AnalysisRun, run_id)
        assert run.commit_sha == sha and run.status in ("completed", "partial") and run.progress == 100
        file_count = session.scalar(select(func.count()).select_from(SourceNode).where(SourceNode.run_id == run_id))
        symbol_count = session.scalar(select(func.count()).select_from(CodeSymbol).where(CodeSymbol.run_id == run_id))
        assert file_count > 0 and symbol_count > 0
        if url == URL:
            assert file_count > 100 and symbol_count > 100
        assert session.scalar(select(func.count()).select_from(CodeReference).where(CodeReference.run_id == run_id)) > 0
