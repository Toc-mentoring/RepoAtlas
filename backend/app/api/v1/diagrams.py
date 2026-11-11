"""다이어그램 API 창구 (docs/API_SPEC.md A10~A12)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.api.errors import ApiError
from backend.app.models import DiagramView
from backend.app.schemas.diagram import DiagramCreate, DiagramTypeItem, DiagramTypesResponse, GraphDTO
from backend.app.services.graphs import (
    availability_of,
    build_graph,
    diagram_availability,
    normalize_options,
    options_hash,
)
from backend.app.services.runs import ReadyRun, get_ready_run

analysis_diagrams_router = APIRouter(prefix="/analyses", tags=["diagrams"])
diagrams_router = APIRouter(prefix="/diagrams", tags=["diagrams"])


def _build_payload(db: Session, ready: ReadyRun, diagram_type: str, options: dict) -> dict:
    """지도를 만들어 저장할 내용(payload)으로 정리한다."""
    graph = build_graph(db, ready, diagram_type, options)
    return {
        "availability": "partial" if ready.run.status == "partial" else "available",
        "truncated": graph.truncated,
        "has_more": graph.truncated,
        "nodes": graph.nodes,
        "edges": graph.edges,
        "warnings": graph.warnings,
        "unresolved_references": graph.unresolved_references,
    }


def _graph_dto(view: DiagramView) -> GraphDTO:
    """저장된 지도(payload)를 응답 모양으로 꺼낸다."""
    return GraphDTO(diagram_id=view.id, run_id=view.run_id, type=view.diagram_type, **view.payload)


@analysis_diagrams_router.get("/{run_id}/diagram-types", response_model=DiagramTypesResponse)
def list_diagram_types(run_id: UUID, db: Session = Depends(get_db)) -> DiagramTypesResponse:
    ready = get_ready_run(db, run_id)
    items = [DiagramTypeItem(**item) for item in diagram_availability(db, ready.run.id)]
    return DiagramTypesResponse(run_id=ready.run.id, items=items)


@analysis_diagrams_router.post(
    "/{run_id}/diagrams",
    response_model=GraphDTO,
    status_code=status.HTTP_201_CREATED,
)
def create_diagram(
    run_id: UUID,
    body: DiagramCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> GraphDTO:
    # ① 결과를 볼 수 있는 분석인지
    ready = get_ready_run(db, run_id)

    # ② 이 분석에서 그릴 수 있는 종류인지
    availability = availability_of(db, run_id, body.type)
    if availability["availability"] == "unsupported":
        raise ApiError(
            409,
            "DIAGRAM_UNSUPPORTED",
            "이 분석에서는 해당 다이어그램을 만들 수 없습니다.",
            {"type": body.type, "reason": availability["reason"]},
        )

    # ③ 옵션 정리 → 같은 옵션이면 같은 다이어그램(캐시)
    options = normalize_options(db, run_id, body.type, body.options)
    digest = options_hash(options)
    find = select(DiagramView).where(
        DiagramView.run_id == run_id,
        DiagramView.diagram_type == body.type,
        DiagramView.options_hash == digest,
    )
    view = db.execute(find).scalar_one_or_none()
    if view is not None:
        response.status_code = status.HTTP_200_OK
        return _graph_dto(view)

    # ④ 새로 만들어서 저장
    payload = _build_payload(db, ready, body.type, options)
    view = DiagramView(run_id=run_id, diagram_type=body.type, options_hash=digest, options=options, payload=payload)
    db.add(view)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        view = db.execute(find).scalar_one_or_none()
        if view is None:
            raise
        response.status_code = status.HTTP_200_OK
        return _graph_dto(view)
    db.refresh(view)
    return _graph_dto(view)


@diagrams_router.get("/{diagram_id}", response_model=GraphDTO)
def get_diagram(diagram_id: UUID, db: Session = Depends(get_db)) -> GraphDTO:
    view = db.get(DiagramView, diagram_id)
    if view is None:
        raise ApiError(404, "DIAGRAM_NOT_FOUND", "다이어그램을 찾을 수 없습니다.", {"diagram_id": str(diagram_id)})
    return _graph_dto(view)
