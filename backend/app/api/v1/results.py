"""분석 결과 조회 API 창구 (docs/API_SPEC.md A07~A09)."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Integer, cast, literal_column, null, or_, select, union_all
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.api.errors import ApiError
from backend.app.api.pagination import decode_cursor, page
from backend.app.models import CodeSymbol, SourceNode
from backend.app.schemas.results import (
    NodeItem,
    NodeListResponse,
    SearchItem,
    SearchResponse,
    SymbolItem,
    SymbolListResponse,
)
from backend.app.services.runs import get_ready_run
from backend.app.services.tree import get_root_node, within

router = APIRouter(prefix="/analyses", tags=["results"])


@router.get("/{run_id}/nodes", response_model=NodeListResponse)
def list_nodes(
    run_id: UUID,
    root_path: str = Query(".", max_length=1000),
    depth: int = Query(2, ge=1, le=8),
    limit: int = Query(100, ge=1, le=100),
    cursor: str | None = Query(None, max_length=200),
    db: Session = Depends(get_db),
) -> NodeListResponse:
    ready = get_ready_run(db, run_id)
    root = get_root_node(db, run_id, root_path)
    offset = decode_cursor(cursor)

    stmt = (
        select(SourceNode)
        .where(SourceNode.run_id == run_id, within(root, depth))
        .order_by(SourceNode.path.asc(), SourceNode.id.asc())
        .offset(offset)
        .limit(limit + 1)
    )
    rows, next_cursor = page(db.execute(stmt).scalars().all(), offset, limit)
    items = [
        NodeItem(
            id=node.id,
            parent_id=node.parent_id,
            kind=node.kind,
            path=node.path,
            # 루트(".")는 저장소 이름으로 보여준다.
            name=ready.repo.name if node.path == "." else node.name,
            language=node.language,
            parse_status=node.parse_status,
        )
        for node in rows
    ]
    return NodeListResponse(items=items, next_cursor=next_cursor)


@router.get("/{run_id}/symbols", response_model=SymbolListResponse)
def list_symbols(
    run_id: UUID,
    file_id: int | None = Query(None, ge=1),
    kind: Literal["function", "class", "method", "interface"] | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None, max_length=200),
    db: Session = Depends(get_db),
) -> SymbolListResponse:
    ready = get_ready_run(db, run_id)
    offset = decode_cursor(cursor)

    if file_id is not None:
        file = db.get(SourceNode, file_id)
        if file is None or file.run_id != run_id or file.kind != "file":
            raise ApiError(404, "FILE_NOT_FOUND", "파일을 찾을 수 없습니다.", {"file_id": file_id})

    stmt = (
        select(CodeSymbol, SourceNode.path)
        .join(SourceNode, SourceNode.id == CodeSymbol.file_id)
        .where(CodeSymbol.run_id == run_id)
    )
    if file_id is not None:
        stmt = stmt.where(CodeSymbol.file_id == file_id)
    if kind is not None:
        stmt = stmt.where(CodeSymbol.kind == kind)
    stmt = (
        stmt.order_by(SourceNode.path.asc(), CodeSymbol.start_line.asc(), CodeSymbol.id.asc())
        .offset(offset)
        .limit(limit + 1)
    )

    rows, next_cursor = page(db.execute(stmt).all(), offset, limit)
    items = [
        SymbolItem(
            id=symbol.id,
            file_id=symbol.file_id,
            parent_symbol_id=symbol.parent_symbol_id,
            kind=symbol.kind,
            name=symbol.name,
            qualified_name=symbol.qualified_name,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            github_url=ready.github_url(path, "file", symbol.start_line, symbol.end_line),
        )
        for symbol, path in rows
    ]
    return SymbolListResponse(items=items, next_cursor=next_cursor)


@router.get("/{run_id}/search", response_model=SearchResponse)
def search(
    run_id: UUID,
    q: str = Query(..., min_length=2, max_length=100),
    kind: Literal["all", "file", "symbol"] = Query("all"),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None, max_length=200),
    db: Session = Depends(get_db),
) -> SearchResponse:
    get_ready_run(db, run_id)
    offset = decode_cursor(cursor)
    term = q.strip()
    if len(term) < 2:
        raise ApiError(422, "INVALID_FILTER", "검색어는 2자 이상이어야 합니다.", {"q": q})

    parts = []
    if kind in ("all", "file"):
        parts.append(
            select(
                literal_column("0").label("rank"),
                literal_column("'file'").label("kind"),
                SourceNode.id.label("item_id"),
                SourceNode.path.label("label"),
                SourceNode.path.label("path"),
                cast(null(), Integer).label("line"),
            ).where(
                SourceNode.run_id == run_id,
                SourceNode.kind == "file",
                SourceNode.path.icontains(term, autoescape=True),
            )
        )
    if kind in ("all", "symbol"):
        parts.append(
            select(
                literal_column("1").label("rank"),
                literal_column("'symbol'").label("kind"),
                CodeSymbol.id.label("item_id"),
                CodeSymbol.qualified_name.label("label"),
                SourceNode.path.label("path"),
                CodeSymbol.start_line.label("line"),
            )
            .join(SourceNode, SourceNode.id == CodeSymbol.file_id)
            .where(
                CodeSymbol.run_id == run_id,
                or_(
                    CodeSymbol.name.icontains(term, autoescape=True),
                    CodeSymbol.qualified_name.icontains(term, autoescape=True),
                ),
            )
        )

    combined = (union_all(*parts) if len(parts) > 1 else parts[0]).subquery()
    stmt = (
        select(combined)
        .order_by(combined.c.rank, combined.c.label, combined.c.item_id)
        .offset(offset)
        .limit(limit + 1)
    )
    rows, next_cursor = page(db.execute(stmt).all(), offset, limit)
    items = [
        SearchItem(kind=row.kind, id=f"{row.kind}:{row.item_id}", label=row.label, path=row.path, line=row.line)
        for row in rows
    ]
    return SearchResponse(items=items, next_cursor=next_cursor)
