"""분석 실행 API의 응답 양식 (docs/API_SPEC.md A04~A06 기준)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


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
