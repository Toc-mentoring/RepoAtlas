"""저장소 API의 요청·응답 양식 (docs/API_SPEC.md A01~A03 기준)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RepositoryCreate(BaseModel):
    url: str = Field(min_length=1, max_length=300)


class RepositoryCreated(BaseModel):
    id: UUID
    provider: str
    owner: str
    name: str
    canonical_url: str
    default_branch: str
    is_existing: bool
    created_at: datetime


class RepositoryDetail(BaseModel):
    id: UUID
    provider: str
    owner: str
    name: str
    canonical_url: str
    default_branch: str
    latest_run_id: UUID | None
    created_at: datetime


class RepositoryListItem(BaseModel):
    id: UUID
    owner: str
    name: str
    default_branch: str
    latest_run_id: UUID | None


class RepositoryListResponse(BaseModel):
    items: list[RepositoryListItem]
    next_cursor: str | None
