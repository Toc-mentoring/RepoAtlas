"""저장소 API의 응답 양식 (docs/API_SPEC.md A02 기준)."""

from uuid import UUID

from pydantic import BaseModel


class RepositoryListItem(BaseModel):
    id: UUID
    owner: str
    name: str
    default_branch: str
    latest_run_id: UUID | None


class RepositoryListResponse(BaseModel):
    items: list[RepositoryListItem]
    next_cursor: str | None
