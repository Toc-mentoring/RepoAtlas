"""분석 결과 조회 API의 응답 양식 (docs/API_SPEC.md A07~A09)."""

from pydantic import BaseModel


class NodeItem(BaseModel):
    id: int
    parent_id: int | None
    kind: str
    path: str
    name: str
    language: str | None
    parse_status: str


class NodeListResponse(BaseModel):
    items: list[NodeItem]
    next_cursor: str | None


class SymbolItem(BaseModel):
    id: int
    file_id: int
    parent_symbol_id: int | None
    kind: str
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    github_url: str


class SymbolListResponse(BaseModel):
    items: list[SymbolItem]
    next_cursor: str | None


class SearchItem(BaseModel):
    kind: str
    id: str
    label: str
    path: str
    line: int | None


class SearchResponse(BaseModel):
    items: list[SearchItem]
    next_cursor: str | None
