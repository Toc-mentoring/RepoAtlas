"""Consume queued analysis runs from PostgreSQL."""

import argparse
import logging
import time

from sqlalchemy.exc import SQLAlchemyError

from backend.app.db.session import make_engine
from worker.archive import ArchiveLimits
from worker.github import AnalysisError
from worker.jobs import LostLease, claim_next, heartbeat, mark_failed, recover_stale, update_progress
from worker.persistence import persist_analysis
from worker.runner import run_analysis

logger = logging.getLogger("repoatlas.worker")
HEARTBEAT_SECONDS = 5


def process_claim(engine, claim, limits: ArchiveLimits) -> bool:
    last_heartbeat = time.monotonic()

    def on_progress(state, progress):
        nonlocal last_heartbeat
        update_progress(engine, claim, state, progress)
        last_heartbeat = time.monotonic()
        logger.info("run=%s state=%s progress=%s", claim.run_id, state, progress)

    def on_tick():
        nonlocal last_heartbeat
        if time.monotonic() - last_heartbeat >= HEARTBEAT_SECONDS:
            heartbeat(engine, claim)
            last_heartbeat = time.monotonic()

    try:
        result = run_analysis(claim.repository_url, claim.commit_sha, limits, on_progress=on_progress, on_tick=on_tick)
        persist_analysis(engine, claim, result)
        logger.info("run=%s state=%s", claim.run_id, result["status"])
        return True
    except LostLease:
        logger.warning("run=%s lease lost; discarding result", claim.run_id)
        return False
    except Exception as exc:
        code = exc.code if isinstance(exc, AnalysisError) else "ANALYSIS_FAILED"
        message = str(exc) if isinstance(exc, AnalysisError) else "Analysis could not be completed"
        try:
            mark_failed(engine, claim, code, message)
        except LostLease:
            logger.warning("run=%s lease lost before failure could be recorded", claim.run_id)
            return False
        logger.error("run=%s state=failed code=%s", claim.run_id, code)
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the RepoAtlas PostgreSQL analysis worker")
    parser.add_argument("--once", action="store_true", help="process at most one queued job and exit")
    parser.add_argument("--poll-seconds", type=float, default=2, help="delay between queue checks")
    parser.add_argument("--stale-seconds", type=int, default=45, help="heartbeat age before retry")
    args = parser.parse_args(argv)
    if args.poll_seconds <= 0 or args.stale_seconds <= 2 * HEARTBEAT_SECONDS:
        parser.error("poll-seconds must be positive and stale-seconds must exceed twice the heartbeat interval")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        engine = make_engine()
        limits = ArchiveLimits.from_environment()
    except (ValueError, RuntimeError, SQLAlchemyError):
        logger.error("Worker configuration error: check DATABASE_URL and resource limits")
        return 1
    try:
        while True:
            try:
                recovered = recover_stale(engine, args.stale_seconds)
                if recovered:
                    logger.info("recovered_or_failed_stale_runs=%s", recovered)
                claim = claim_next(engine)
                if claim:
                    success = process_claim(engine, claim, limits)
                    if args.once:
                        return 0 if success else 1
                elif args.once:
                    logger.info("No queued analysis runs")
                    return 0
                else:
                    time.sleep(args.poll_seconds)
            except SQLAlchemyError:
                logger.error("PostgreSQL operation failed; check the database connection and migration")
                if args.once:
                    return 1
                time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        logger.info("Worker stopped")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
