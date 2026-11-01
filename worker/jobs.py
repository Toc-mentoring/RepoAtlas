"""PostgreSQL job claims, progress and stale-worker recovery."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.app.models import AnalysisRun, Repository

ACTIVE_STATES = ("fetching", "parsing", "resolving")


class LostLease(Exception):
    """The job was recovered or claimed by another worker."""


@dataclass(frozen=True)
class JobClaim:
    run_id: UUID
    repository_url: str
    commit_sha: str
    attempt: int


def claim_next(engine: Engine) -> JobClaim | None:
    with Session(engine) as session, session.begin():
        run = session.scalar(
            select(AnalysisRun).where(AnalysisRun.status == "queued")
            .order_by(AnalysisRun.created_at, AnalysisRun.id)
            .with_for_update(skip_locked=True).limit(1)
        )
        if run is None:
            return None
        repo = session.get(Repository, run.repository_id)
        run.status = "fetching"
        run.progress = 0
        run.attempts += 1
        run.started_at = func.now()
        run.heartbeat_at = func.now()
        run.finished_at = None
        run.error_code = None
        run.error_message = None
        return JobClaim(run.id, repo.canonical_url, run.commit_sha, run.attempts)


def recover_stale(engine: Engine, stale_seconds: int) -> int:
    if stale_seconds <= 0:
        raise ValueError("stale_seconds must be positive")
    with Session(engine) as session, session.begin():
        runs = session.scalars(
            select(AnalysisRun).where(
                AnalysisRun.status.in_(ACTIVE_STATES),
                or_(AnalysisRun.heartbeat_at.is_(None),
                    AnalysisRun.heartbeat_at < func.now() - timedelta(seconds=stale_seconds)),
            ).with_for_update(skip_locked=True)
        ).all()
        for run in runs:
            if run.attempts < 2:
                run.status = "queued"
                run.progress = 0
                run.heartbeat_at = None
                run.error_code = None
                run.error_message = None
            else:
                run.status = "failed"
                run.error_code = "WORKER_STALE"
                run.error_message = "Worker stopped responding after the retry"
                run.finished_at = func.now()
        return len(runs)


def _update_owned(engine: Engine, claim: JobClaim, values: dict, allowed_states=ACTIVE_STATES) -> None:
    with engine.begin() as connection:
        result = connection.execute(
            update(AnalysisRun).where(AnalysisRun.id == claim.run_id, AnalysisRun.attempts == claim.attempt,
                                      AnalysisRun.status.in_(allowed_states)).values(**values)
        )
        if result.rowcount != 1:
            raise LostLease(f"Analysis run {claim.run_id} is no longer owned by this worker")


def update_progress(engine: Engine, claim: JobClaim, state: str, progress: int) -> None:
    previous = {"fetching": ("fetching",), "parsing": ("fetching", "parsing"),
                "resolving": ("parsing", "resolving")}
    if state not in previous or not 0 <= progress < 100:
        raise ValueError("Invalid worker progress")
    _update_owned(engine, claim, {"status": state, "progress": progress, "heartbeat_at": func.now()}, previous[state])


def heartbeat(engine: Engine, claim: JobClaim) -> None:
    _update_owned(engine, claim, {"heartbeat_at": func.now()})


def mark_failed(engine: Engine, claim: JobClaim, code: str, message: str) -> None:
    _update_owned(engine, claim, {"status": "failed", "error_code": code, "error_message": message[:500],
                                  "finished_at": func.now(), "heartbeat_at": func.now()})
