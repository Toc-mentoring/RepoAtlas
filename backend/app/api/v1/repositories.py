"""저장소 관련 API 창구 (docs/API_SPEC.md A01~A03)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.models import AnalysisRun, Repository
from backend.app.schemas.repository import RepositoryListItem, RepositoryListResponse

router = APIRouter(prefix="/repositories", tags=["repositories"])


@router.get("", response_model=RepositoryListResponse)
def list_repositories(
    limit: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, max_length=200),
    db: Session = Depends(get_db),
) -> RepositoryListResponse:
    # 저장소마다 가장 최근 분석 실행(run)의 id를 함께 가져온다.
    latest_run_id = (
        select(AnalysisRun.id)
        .where(AnalysisRun.repository_id == Repository.id)
        .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
        .limit(1)
        .scalar_subquery()
    )

    stmt = (
        select(Repository, latest_run_id.label("latest_run_id"))
        .order_by(Repository.created_at.desc(), Repository.id.desc())
        .limit(limit)
    )

    # q가 있으면 owner 또는 name에 그 글자가 들어간 저장소만 남긴다.
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(Repository.owner.ilike(pattern), Repository.name.ilike(pattern)))

    rows = db.execute(stmt).all()

    items = [
        RepositoryListItem(
            id=repo.id,
            owner=repo.owner,
            name=repo.name,
            default_branch=repo.default_branch,
            latest_run_id=run_id,
        )
        for repo, run_id in rows
    ]
    # TODO: cursor 페이지 넘기기는 다음 작업에서 구현한다.
    return RepositoryListResponse(items=items, next_cursor=None)
