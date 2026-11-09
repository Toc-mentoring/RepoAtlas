"""분석 실행(run)을 꺼내고, 결과를 볼 수 있는 상태인지 확인한다."""

from dataclasses import dataclass
from urllib.parse import quote
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.api.errors import ApiError
from backend.app.models import AnalysisRun, Repository

READY_STATUSES = ("completed", "partial")


@dataclass
class ReadyRun:
    run: AnalysisRun
    repo: Repository

    def github_url(self, path: str, kind: str = "file", start_line: int | None = None, end_line: int | None = None) -> str:
        base = self.repo.canonical_url
        sha = self.run.commit_sha
        if path == ".":
            return f"{base}/tree/{sha}"
        mode = "tree" if kind == "directory" else "blob"
        url = f"{base}/{mode}/{sha}/{quote(path)}"
        if start_line is not None:
            url += f"#L{start_line}"
            if end_line is not None and end_line != start_line:
                url += f"-L{end_line}"
        return url


def get_run_or_404(db: Session, run_id: UUID) -> AnalysisRun:
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise ApiError(404, "ANALYSIS_NOT_FOUND", "분석 실행을 찾을 수 없습니다.", {"run_id": str(run_id)})
    return run


def get_ready_run(db: Session, run_id: UUID) -> ReadyRun:
    """결과 조회가 가능한(completed/partial) 실행만 돌려준다."""
    run = get_run_or_404(db, run_id)
    if run.status not in READY_STATUSES:
        raise ApiError(
            409,
            "ANALYSIS_NOT_READY",
            "분석이 아직 완료되지 않았습니다." if run.status != "failed" else "실패한 분석은 결과를 조회할 수 없습니다.",
            {"status": run.status},
        )
    repo = db.get(Repository, run.repository_id)
    return ReadyRun(run=run, repo=repo)
