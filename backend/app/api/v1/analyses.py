"""분석 실행 관련 API 창구 (docs/API_SPEC.md A04~A06)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db, get_github_client
from backend.app.api.errors import ApiError
from backend.app.models import AnalysisRun, Repository
from backend.app.schemas.analysis import (
    AnalysisAccepted,
    AnalysisDetail,
    AnalysisListItem,
    AnalysisListResponse,
)
from backend.app.services.github import GitHubClient, RepoRef

# 같은 커밋이면 새로 만들지 않고 재사용하는 상태 (진행 중 + 완료)
REUSABLE_STATUSES = ("queued", "fetching", "parsing", "resolving", "completed")

repository_analyses_router = APIRouter(prefix="/repositories", tags=["analyses"])
analyses_router = APIRouter(prefix="/analyses", tags=["analyses"])


def _get_repository_or_404(db: Session, repo_id: UUID) -> Repository:
    repo = db.get(Repository, repo_id)
    if repo is None:
        raise ApiError(404, "REPOSITORY_NOT_FOUND", "저장소를 찾을 수 없습니다.", {"repo_id": str(repo_id)})
    return repo


def _find_reusable_run(db: Session, repo_id: UUID, commit_sha: str) -> AnalysisRun | None:
    stmt = (
        select(AnalysisRun)
        .where(
            AnalysisRun.repository_id == repo_id,
            AnalysisRun.commit_sha == commit_sha,
            AnalysisRun.status.in_(REUSABLE_STATUSES),
        )
        .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def _accepted(run: AnalysisRun, reused: bool) -> AnalysisAccepted:
    return AnalysisAccepted(
        run_id=run.id,
        repository_id=run.repository_id,
        commit_sha=run.commit_sha,
        status=run.status,
        reused=reused,
        status_url=f"/api/v1/analyses/{run.id}",
    )


@repository_analyses_router.post(
    "/{repo_id}/analyses",
    response_model=AnalysisAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_analysis(
    repo_id: UUID,
    response: Response,
    db: Session = Depends(get_db),
    github: GitHubClient = Depends(get_github_client),
) -> AnalysisAccepted:
    # ① 등록된 저장소인지 확인
    repo = _get_repository_or_404(db, repo_id)

    # ② 기본 브랜치의 지금 커밋(SHA)을 GitHub에서 받아 고정
    commit_sha = github.get_branch_head_sha(RepoRef(repo.owner, repo.name), repo.default_branch)

    # ③ 같은 커밋으로 진행 중이거나 끝난 분석이 있으면 재사용
    existing = _find_reusable_run(db, repo.id, commit_sha)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return _accepted(existing, reused=True)

    # ④ 새 분석 작업 등록 (status=queued → Worker가 가져감)
    run = AnalysisRun(repository_id=repo.id, commit_sha=commit_sha)
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        # 동시에 같은 요청이 들어와 이미 만들어진 경우
        db.rollback()
        existing = _find_reusable_run(db, repo.id, commit_sha)
        if existing is None:
            raise
        response.status_code = status.HTTP_200_OK
        return _accepted(existing, reused=True)
    db.refresh(run)
    return _accepted(run, reused=False)


@repository_analyses_router.get("/{repo_id}/analyses", response_model=AnalysisListResponse)
def list_analyses(
    repo_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> AnalysisListResponse:
    _get_repository_or_404(db, repo_id)
    stmt = (
        select(AnalysisRun)
        .where(AnalysisRun.repository_id == repo_id)
        .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
        .limit(limit)
    )
    runs = db.execute(stmt).scalars().all()
    items = [
        AnalysisListItem(
            id=run.id,
            commit_sha=run.commit_sha,
            status=run.status,
            progress=run.progress,
            created_at=run.created_at,
        )
        for run in runs
    ]
    # TODO: cursor 페이지 넘기기는 다음 작업에서 구현한다.
    return AnalysisListResponse(items=items, next_cursor=None)


@analyses_router.get("/{run_id}", response_model=AnalysisDetail)
def get_analysis(run_id: UUID, db: Session = Depends(get_db)) -> AnalysisDetail:
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise ApiError(404, "ANALYSIS_NOT_FOUND", "분석 실행을 찾을 수 없습니다.", {"run_id": str(run_id)})
    return AnalysisDetail(
        id=run.id,
        repository_id=run.repository_id,
        commit_sha=run.commit_sha,
        status=run.status,
        progress=run.progress,
        stats=run.stats or {},
        warnings=run.warnings or [],
        error_code=run.error_code,
        error_message=run.error_message,
        created_at=run.created_at,
        finished_at=run.finished_at,
    )
