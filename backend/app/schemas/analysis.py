"""분석 실행 API의 응답 양식 (docs/API_SPEC.md A04~A06 기준)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

class AnalysisRequest(BaseModel):
    """A04 분석 요청 주문서. commit_sha를 안 보내면 기본 브랜치 최신 커밋을 분석한다."""

    commit_sha: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{40}$")


class AnalysisAccepted(BaseModel):
    run_id: UUID
    repository_id: UUID
    commit_sha: str
    status: str
    reused: bool
    status_url: str


class AnalysisListItem(BaseModel):
    id: UUID
    commit_sha: str
    status: str
    progress: int
    created_at: datetime


class AnalysisListResponse(BaseModel):
    items: list[AnalysisListItem]
    next_cursor: str | None


class AnalysisDetail(BaseModel):
    id: UUID
    repository_id: UUID
    commit_sha: str
    status: str
    progress: int
    stats: dict[str, Any]
    warnings: list[Any]
    error_code: str | None
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None
