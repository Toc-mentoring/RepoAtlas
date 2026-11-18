"""저장소 관련 API 창구 (docs/API_SPEC.md A01~A03)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db, get_github_client
from backend.app.api.errors import ApiError
from backend.app.api.pagination import decode_cursor, page
from backend.app.models import AnalysisRun, Repository
from backend.app.schemas.repository import (
    RepositoryCreate,
    RepositoryCreated,
    RepositoryDetail,
    RepositoryListItem,
    RepositoryListResponse,
)
from backend.app.services.github import GitHubClient, parse_github_url

router = APIRouter(prefix="/repositories", tags=["repositories"])


def _latest_run_id():
    # 저장소마다 가장 최근 분석 실행(run)의 id
    return (
        select(AnalysisRun.id)
        .where(AnalysisRun.repository_id == Repository.id)
        .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
        .limit(1)
        .scalar_subquery()
    )


def _find_by_url(db: Session, canonical_url: str) -> Repository | None:
    stmt = select(Repository).where(func.lower(Repository.canonical_url) == canonical_url.lower())
    return db.execute(stmt).scalar_one_or_none()


def _created(repo: Repository, is_existing: bool) -> RepositoryCreated:
    return RepositoryCreated(
        id=repo.id,
        provider=repo.provider,
        owner=repo.owner,
        name=repo.name,
        canonical_url=repo.canonical_url,
        default_branch=repo.default_branch,
        is_existing=is_existing,
        created_at=repo.created_at,
    )


@router.post("", response_model=RepositoryCreated, status_code=status.HTTP_201_CREATED)
def register_repository(
    body: RepositoryCreate,
    response: Response,
    db: Session = Depends(get_db),
    github: GitHubClient = Depends(get_github_client),
) -> RepositoryCreated:
    # ① 주소 모양 검사
    ref = parse_github_url(body.url)

    # ② 이미 등록된 주소면 GitHub에 묻지 않고 그대로 돌려준다.
    existing = _find_by_url(db, ref.canonical_url)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return _created(existing, is_existing=True)

    # ③ GitHub에 실제로 있는 공개 저장소인지 확인
    info = github.get_repository(ref)

    # 대소문자나 이름 변경으로 주소가 달라졌을 수 있어 한 번 더 확인
    existing = _find_by_url(db, info.canonical_url)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return _created(existing, is_existing=True)

    # ④ 창고(DB)에 한 줄 추가
    repo = Repository(
        owner=info.owner,
        name=info.name,
        canonical_url=info.canonical_url,
        default_branch=info.default_branch,
    )
    db.add(repo)
    try:
        db.commit()
    except IntegrityError:
        # 동시에 같은 주소가 등록된 경우
        db.rollback()
        existing = _find_by_url(db, info.canonical_url)
        if existing is None:
            raise
        response.status_code = status.HTTP_200_OK
        return _created(existing, is_existing=True)
    db.refresh(repo)

    # ⑤ 대답
    return _created(repo, is_existing=False)


@router.get("", response_model=RepositoryListResponse)
def list_repositories(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None, max_length=200),
    q: str | None = Query(None, max_length=200),
    db: Session = Depends(get_db),
) -> RepositoryListResponse:
    # ① 책갈피를 풀어서 "몇 개 건너뛸지" 알아내기 (처음이면 0)
    offset = decode_cursor(cursor)

    # ② 건너뛰고, 하나 더(limit + 1) 읽어오는 주문서 만들기
    stmt = (
        select(Repository, _latest_run_id().label("latest_run_id"))
        .order_by(Repository.created_at.desc(), Repository.id.desc())
        .offset(offset)
        .limit(limit + 1)
    )

    # q가 있으면 owner 또는 name에 그 글자가 들어간 저장소만 남긴다.
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(Repository.owner.ilike(pattern), Repository.name.ilike(pattern)))

    # ③ 읽어온 것 중 limit개만 남기고, 더 있으면 다음 책갈피 만들기
    rows, next_cursor = page(db.execute(stmt).all(), offset, limit)

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
    return RepositoryListResponse(items=items, next_cursor=next_cursor)


@router.get("/{repo_id}", response_model=RepositoryDetail)
def get_repository(repo_id: UUID, db: Session = Depends(get_db)) -> RepositoryDetail:
    stmt = select(Repository, _latest_run_id().label("latest_run_id")).where(Repository.id == repo_id)
    row = db.execute(stmt).first()
    if row is None:
        raise ApiError(404, "REPOSITORY_NOT_FOUND", "저장소를 찾을 수 없습니다.", {"repo_id": str(repo_id)})

    repo, run_id = row
    return RepositoryDetail(
        id=repo.id,
        provider=repo.provider,
        owner=repo.owner,
        name=repo.name,
        canonical_url=repo.canonical_url,
        default_branch=repo.default_branch,
        latest_run_id=run_id,
        created_at=repo.created_at,
    )
