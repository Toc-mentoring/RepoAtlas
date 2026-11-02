from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import AnalysisRun, Repository
from worker.jobs import LostLease, claim_next, heartbeat, mark_failed, recover_stale, update_progress


def queued_runs(engine):
    with Session(engine) as session, session.begin():
        repo = Repository(owner="example", name="repo", canonical_url="https://github.com/example/repo", default_branch="main")
        session.add(repo)
        session.flush()
        first = AnalysisRun(repository_id=repo.id, commit_sha="a" * 40)
        second = AnalysisRun(repository_id=repo.id, commit_sha="b" * 40)
        session.add_all([first, second])
        session.flush()
        return first.id, second.id


def test_claim_skips_locked_jobs(worker_db):
    first_id, second_id = queued_runs(worker_db)
    with Session(worker_db) as locked, locked.begin():
        locked.execute(select(AnalysisRun).where(AnalysisRun.id == first_id).with_for_update()).one()
        claim = claim_next(worker_db)
        assert claim.run_id == second_id and claim.attempt == 1
    assert claim_next(worker_db).run_id == first_id
    assert claim_next(worker_db) is None


def test_progress_stale_retry_and_lease_fencing(worker_db):
    queued_runs(worker_db)
    claim = claim_next(worker_db)
    update_progress(worker_db, claim, "parsing", 30)
    heartbeat(worker_db, claim)
    with Session(worker_db) as session, session.begin():
        run = session.get(AnalysisRun, claim.run_id)
        assert run.status == "parsing" and run.progress == 30 and run.heartbeat_at is not None
        run.heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert recover_stale(worker_db, 30) == 1
    with pytest.raises(LostLease):
        heartbeat(worker_db, claim)
    # The untouched older queued job can be claimed first.
    other = claim_next(worker_db)
    if other.run_id != claim.run_id:
        mark_failed(worker_db, other, "TEST", "test cleanup")
        other = claim_next(worker_db)
    assert other.run_id == claim.run_id and other.attempt == 2
    with pytest.raises(LostLease):
        update_progress(worker_db, claim, "parsing", 30)
    with Session(worker_db) as session, session.begin():
        session.get(AnalysisRun, other.run_id).heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert recover_stale(worker_db, 30) == 1
    with Session(worker_db) as session:
        run = session.get(AnalysisRun, other.run_id)
        assert run.status == "failed" and run.error_code == "WORKER_STALE" and run.finished_at is not None


def test_failed_job_cannot_be_updated_again(worker_db):
    queued_runs(worker_db)
    claim = claim_next(worker_db)
    mark_failed(worker_db, claim, "LIMIT_EXCEEDED", "Archive exceeds the limit")
    with Session(worker_db) as session:
        run = session.get(AnalysisRun, claim.run_id)
        assert (run.status, run.error_code) == ("failed", "LIMIT_EXCEEDED")
        assert run.finished_at is not None
    with pytest.raises(LostLease):
        heartbeat(worker_db, claim)
