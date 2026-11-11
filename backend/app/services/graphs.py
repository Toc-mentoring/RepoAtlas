"""저장된 분석 결과를 화면용 그래프(GraphDTO의 nodes/edges)로 바꾼다.

지원: directory(폴더 구조), dependency(파일 import 관계), symbols(파일 안 함수·클래스).
architecture, erd는 아직 unsupported로 알려준다.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiError
from backend.app.models import CodeReference, CodeSymbol, SchemaTable, SourceNode
from backend.app.services.runs import ReadyRun
from backend.app.services.tree import get_root_node, within

ALLOWED_OPTIONS = {
    "directory": {"root_path", "depth", "max_nodes"},
    "dependency": {"root_path", "language", "depth", "max_nodes"},
    "symbols": {"file_id", "max_nodes"},
    "architecture": set(),
    "erd": set(),
}

IMPORT_BASIS = {
    "python": "python_ast_import",
    "javascript": "tree_sitter_import",
    "typescript": "tree_sitter_import",
    "tsx": "tree_sitter_import",
    "jsx": "tree_sitter_import",
}


@dataclass
class Graph:
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)
    unresolved_references: int = 0


def _invalid(message: str, **details) -> ApiError:
    return ApiError(422, "INVALID_FILTER", message, details)


def _int_option(options: dict, key: str, default: int, low: int, high: int) -> int:
    value = options.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise _invalid(f"{key}는 {low}~{high} 사이의 정수여야 합니다.", option=key, value=value)
    return value


# ---------------------------------------------------------------- availability


def diagram_availability(db: Session, run_id) -> list[dict[str, Any]]:
    node_count = db.scalar(select(func.count()).select_from(SourceNode).where(SourceNode.run_id == run_id, SourceNode.path != "."))
    ref_total = db.scalar(select(func.count()).select_from(CodeReference).where(CodeReference.run_id == run_id))
    ref_resolved = db.scalar(
        select(func.count())
        .select_from(CodeReference)
        .where(CodeReference.run_id == run_id, CodeReference.resolution_status == "resolved")
    )
    symbol_count = db.scalar(select(func.count()).select_from(CodeSymbol).where(CodeSymbol.run_id == run_id))
    table_count = db.scalar(select(func.count()).select_from(SchemaTable).where(SchemaTable.run_id == run_id))

    def item(kind, ok, reason):
        return {"type": kind, "availability": "available" if ok else "unsupported", "reason": None if ok else reason}

    if ref_total == 0:
        dependency_reason = "정적 import 문을 찾지 못했습니다."
    else:
        dependency_reason = "저장소 내부 파일 사이의 import 관계를 찾지 못했습니다."

    return [
        item("directory", node_count > 0, "분석된 파일이 없습니다."),
        item("dependency", ref_resolved > 0, dependency_reason),
        item("symbols", symbol_count > 0, "함수·클래스를 찾지 못했습니다."),
        item("architecture", False, "설정 파일 기반 시스템 구성도는 아직 지원하지 않습니다."),
        item(
            "erd",
            False,
            "ERD 다이어그램은 아직 지원하지 않습니다." if table_count > 0 else "해석 가능한 SQL DDL 없음",
        ),
    ]


def availability_of(db: Session, run_id, diagram_type: str) -> dict[str, Any]:
    return next(item for item in diagram_availability(db, run_id) if item["type"] == diagram_type)


# ---------------------------------------------------------------- options


def normalize_options(db: Session, run_id, diagram_type: str, options: dict[str, Any]) -> dict[str, Any]:
    """기본값을 채우고 잘못된 옵션을 막는다. 같은 뜻의 옵션은 항상 같은 모양이 된다."""
    unknown = sorted(set(options) - ALLOWED_OPTIONS[diagram_type])
    if unknown:
        raise _invalid("지원하지 않는 옵션입니다.", options=unknown)

    if diagram_type in ("directory", "dependency"):
        root_path = options.get("root_path", ".")
        if not isinstance(root_path, str):
            raise _invalid("root_path는 문자열이어야 합니다.", option="root_path")
        root = get_root_node(db, run_id, root_path, not_found_status=422)
        normalized: dict[str, Any] = {
            "root_path": root.path,
            "depth": _int_option(options, "depth", 2 if diagram_type == "directory" else 8, 1, 8),
            "max_nodes": _int_option(options, "max_nodes", 150, 20, 300),
        }
        if diagram_type == "dependency":
            language = options.get("language")
            if language is not None and (not isinstance(language, str) or not 1 <= len(language.strip()) <= 40):
                raise _invalid("language 값이 올바르지 않습니다.", option="language")
            normalized["language"] = language.strip().lower() if language else None
        return normalized

    if diagram_type == "symbols":
        if "file_id" not in options:
            raise _invalid("symbols 다이어그램은 options.file_id가 필요합니다.", option="file_id")
        file_id = options["file_id"]
        if isinstance(file_id, bool) or not isinstance(file_id, int):
            raise _invalid("file_id는 정수여야 합니다.", option="file_id")
        file = db.get(SourceNode, file_id)
        if file is None or file.run_id != run_id or file.kind != "file":
            raise _invalid("file_id에 해당하는 파일이 없습니다.", option="file_id", value=file_id)
        return {"file_id": file_id, "max_nodes": _int_option(options, "max_nodes", 150, 20, 300)}

    return {}


def options_hash(options: dict[str, Any]) -> str:
    raw = json.dumps(options, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------- builders


def _node_id(node: SourceNode) -> str:
    return f"{'dir' if node.kind == 'directory' else 'file'}:{node.id}"


def _source_node_dto(ready: ReadyRun, node: SourceNode) -> dict[str, Any]:
    return {
        "id": _node_id(node),
        "type": node.kind,
        "label": ready.repo.name if node.path == "." else node.name,
        "data": {
            "path": node.path,
            "language": node.language,
            "parse_status": node.parse_status,
            "github_url": ready.github_url(node.path, node.kind),
        },
    }


def _truncation_warning(max_nodes: int) -> str:
    return f"노드가 많아 {max_nodes}개까지만 표시했습니다."


def build_directory(db: Session, ready: ReadyRun, options: dict[str, Any]) -> Graph:
    run_id = ready.run.id
    root = get_root_node(db, run_id, options["root_path"], not_found_status=422)
    max_nodes = options["max_nodes"]
    rows = db.execute(
        select(SourceNode)
        .where(SourceNode.run_id == run_id, within(root, options["depth"]))
        .order_by(SourceNode.path.asc(), SourceNode.id.asc())
        .limit(max_nodes + 1)
    ).scalars().all()

    graph = Graph()
    if len(rows) > max_nodes:
        rows = rows[:max_nodes]
        graph.truncated = True
        graph.warnings.append(_truncation_warning(max_nodes))

    kept = {node.id: node for node in rows}
    graph.nodes = [_source_node_dto(ready, node) for node in rows]
    graph.edges = [
        {
            "id": f"contains:{kept[node.parent_id].id}:{node.id}",
            "source": _node_id(kept[node.parent_id]),
            "target": _node_id(node),
            "type": "contains",
            "data": {},
        }
        for node in rows
        if node.parent_id in kept
    ]
    return graph


def build_dependency(db: Session, ready: ReadyRun, options: dict[str, Any]) -> Graph:
    run_id = ready.run.id
    root = get_root_node(db, run_id, options["root_path"], not_found_status=422)
    scope = select(SourceNode).where(
        SourceNode.run_id == run_id,
        SourceNode.kind == "file",
        within(root, options["depth"]),
    )
    if options.get("language"):
        scope = scope.where(func.lower(SourceNode.language) == options["language"])
    files = {node.id: node for node in db.execute(scope).scalars().all()}

    graph = Graph()
    if not files:
        return graph

    refs = db.execute(
        select(CodeReference)
        .where(CodeReference.run_id == run_id, CodeReference.source_file_id.in_(list(files)))
        .order_by(CodeReference.source_file_id, CodeReference.source_line, CodeReference.id)
    ).scalars().all()

    edges: dict[str, dict[str, Any]] = {}
    for ref in refs:
        if ref.resolution_status == "unresolved":
            graph.unresolved_references += 1
        if ref.resolution_status != "resolved" or ref.target_file_id not in files:
            continue
        source, target = files[ref.source_file_id], files[ref.target_file_id]
        edge_id = f"imports:{source.id}:{target.id}:{ref.source_line}"
        if edge_id in edges:
            continue
        edges[edge_id] = {
            "id": edge_id,
            "source": _node_id(source),
            "target": _node_id(target),
            "type": "imports",
            "data": {
                "certainty": "confirmed",
                "evidence": [
                    {
                        "path": source.path,
                        "line": ref.source_line,
                        "basis": IMPORT_BASIS.get((source.language or "").lower(), "static_import"),
                        "github_url": ready.github_url(source.path, "file", ref.source_line),
                    }
                ],
            },
        }

    degree: dict[int, int] = {}
    for edge in edges.values():
        for end in (edge["source"], edge["target"]):
            file_id = int(end.split(":")[1])
            degree[file_id] = degree.get(file_id, 0) + 1

    ordered = sorted(degree, key=lambda file_id: (-degree[file_id], files[file_id].path))
    max_nodes = options["max_nodes"]
    if len(ordered) > max_nodes:
        ordered = ordered[:max_nodes]
        graph.truncated = True
        graph.warnings.append(_truncation_warning(max_nodes))

    kept_ids = {f"file:{file_id}" for file_id in ordered}
    graph.nodes = [_source_node_dto(ready, files[file_id]) for file_id in sorted(ordered, key=lambda i: files[i].path)]
    graph.edges = [edge for edge in edges.values() if edge["source"] in kept_ids and edge["target"] in kept_ids]
    if graph.unresolved_references:
        graph.warnings.append(f"해석하지 못한 import {graph.unresolved_references}개는 선으로 표시하지 않았습니다.")
    return graph


def build_symbols(db: Session, ready: ReadyRun, options: dict[str, Any]) -> Graph:
    file = db.get(SourceNode, options["file_id"])
    max_nodes = options["max_nodes"]
    symbols = db.execute(
        select(CodeSymbol)
        .where(CodeSymbol.run_id == ready.run.id, CodeSymbol.file_id == file.id)
        .order_by(CodeSymbol.start_line.asc(), CodeSymbol.id.asc())
        .limit(max_nodes)  # 파일 노드 1개 + 심볼 (max_nodes - 1)개
    ).scalars().all()

    graph = Graph()
    if len(symbols) > max_nodes - 1:
        symbols = symbols[: max_nodes - 1]
        graph.truncated = True
        graph.warnings.append(_truncation_warning(max_nodes))

    graph.nodes.append(_source_node_dto(ready, file))
    kept = {symbol.id for symbol in symbols}
    for symbol in symbols:
        graph.nodes.append(
            {
                "id": f"symbol:{symbol.id}",
                "type": symbol.kind,
                "label": symbol.name,
                "data": {
                    "qualified_name": symbol.qualified_name,
                    "path": file.path,
                    "start_line": symbol.start_line,
                    "end_line": symbol.end_line,
                    "github_url": ready.github_url(file.path, "file", symbol.start_line, symbol.end_line),
                },
            }
        )
        parent = f"symbol:{symbol.parent_symbol_id}" if symbol.parent_symbol_id in kept else f"file:{file.id}"
        graph.edges.append(
            {
                "id": f"contains:{parent}:symbol:{symbol.id}",
                "source": parent,
                "target": f"symbol:{symbol.id}",
                "type": "contains",
                "data": {},
            }
        )
    return graph


BUILDERS = {
    "directory": build_directory,
    "dependency": build_dependency,
    "symbols": build_symbols,
}


def build_graph(db: Session, ready: ReadyRun, diagram_type: str, options: dict[str, Any]) -> Graph:
    graph = BUILDERS[diagram_type](db, ready, options)
    # 부분 분석(partial)일 때의 경고도 함께 보여준다.
    graph.warnings = [*(ready.run.warnings or []), *graph.warnings]
    return graph
