import zipfile

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import AnalysisRun, Repository, SourceNode
from worker.analyzer import analyze_archive
from worker.archive import ArchiveLimits
from worker.github import AnalysisError, parse_repository_url
from worker.jobs import claim_next
from worker import main


def make_claim(engine):
    with Session(engine) as session, session.begin():
        repo = Repository(owner="example", name="repo", canonical_url="https://github.com/example/repo", default_branch="main")
        session.add(repo)
        session.flush()
        session.add(AnalysisRun(repository_id=repo.id, commit_sha="a" * 40))
    return claim_next(engine)


def test_worker_processes_registered_job(worker_db, tmp_path, monkeypatch):
    claim = make_claim(worker_db)
    archive_path = tmp_path / "repo.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("repo-sha/main.py", "def run(): pass\n")
    result = analyze_archive(archive_path, parse_repository_url(claim.repository_url), claim.commit_sha, ArchiveLimits())

    def fake_run(url, sha, limits, *, on_progress, on_tick):
        on_progress("fetching", 5)
        on_progress("parsing", 30)
        on_progress("resolving", 75)
        on_tick()
        return result

    monkeypatch.setattr(main, "run_analysis", fake_run)
    assert main.process_claim(worker_db, claim, ArchiveLimits()) is True
    with Session(worker_db) as session:
        run = session.get(AnalysisRun, claim.run_id)
        assert run.status == "completed" and run.progress == 100
        assert session.scalar(select(SourceNode).where(SourceNode.run_id == run.id, SourceNode.path == "main.py")) is not None


def test_worker_marks_analysis_errors_failed(worker_db, monkeypatch):
    claim = make_claim(worker_db)

    def fail(*args, **kwargs):
        raise AnalysisError("GITHUB_NOT_FOUND", "Public repository or commit was not found")

    monkeypatch.setattr(main, "run_analysis", fail)
    assert main.process_claim(worker_db, claim, ArchiveLimits()) is False
    with Session(worker_db) as session:
        run = session.get(AnalysisRun, claim.run_id)
        assert (run.status, run.error_code) == ("failed", "GITHUB_NOT_FOUND")
        assert run.finished_at is not None


def test_invalid_configuration_does_not_log_credentials(monkeypatch, caplog):
    monkeypatch.setenv("DATABASE_URL", "not-a-postgres-url-secretvalue")
    assert main.main(["--once"]) == 1
    assert "secretvalue" not in caplog.text
