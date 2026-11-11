"""다이어그램 API의 요청·응답 양식 (docs/API_SPEC.md A10~A12)."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

DiagramType = Literal["directory", "dependency", "symbols", "architecture", "erd"]


class DiagramTypeItem(BaseModel):
    type: DiagramType
    availability: Literal["available", "partial", "unsupported"]
    reason: str | None


class DiagramTypesResponse(BaseModel):
    run_id: UUID
    items: list[DiagramTypeItem]


class DiagramCreate(BaseModel):
    type: DiagramType
    options: dict[str, Any] = Field(default_factory=dict)


class GraphDTO(BaseModel):
    diagram_id: UUID
    run_id: UUID
    type: DiagramType
    availability: Literal["available", "partial", "unsupported"]
    truncated: bool
    has_more: bool
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    warnings: list[Any]
    unresolved_references: int
