"""저장된 분석 결과를 화면용 그래프(GraphDTO의 nodes/edges)로 바꾼다.

지원: directory(폴더 구조), dependency(파일 import 관계), symbols(파일 안 함수·클래스),
architecture(설정 파일로 본 시스템 구성), erd(SQL DDL로 본 DB 표 구조).
"""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiError
from backend.app.models import CodeReference, CodeSymbol, SchemaColumn, SchemaForeignKey, SchemaTable, SourceNode
from backend.app.services.runs import ReadyRun
from backend.app.services.tree import get_root_node, within

ALLOWED_OPTIONS = {
    "directory": {"root_path", "depth", "max_nodes"},
    "dependency": {"root_path", "language", "depth", "max_nodes"},
    "symbols": {"file_id", "max_nodes"},
    "architecture": {"max_nodes"},  # 그릴 노드 최대 개수만 받는다
    "erd": {"max_nodes"},
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
        _architecture_availability(db, run_id),
        # Worker가 .sql 파일에서 CREATE TABLE을 하나라도 찾았으면 ERD를 그릴 수 있다.
        item("erd", table_count > 0, "해석 가능한 SQL DDL 없음"),
    ]


def _architecture_availability(db: Session, run_id) -> dict[str, Any]:
    """설정 파일 단서가 얼마나 있는지에 따라 architecture 가용성을 3단계로 알려준다."""
    facts = [fact for _, file_facts in _config_facts(db, run_id) for fact in file_facts]
    if any(fact.get("kind") == "service" for fact in facts):
        # docker-compose의 services가 있으면 구성 요소와 연결(depends_on)까지 그릴 수 있다.
        return {"type": "architecture", "availability": "available", "reason": None}
    if facts:
        # package.json, Dockerfile, FastAPI 앱 같은 단서만 있으면 구성 요소만 그린다(연결선 없음).
        return {"type": "architecture", "availability": "partial",
                "reason": "docker-compose가 없어 구성 요소만 표시하고 연결은 표시하지 않습니다."}
    return {"type": "architecture", "availability": "unsupported",
            "reason": "시스템 구성을 알 수 있는 설정 파일(docker-compose 등)을 찾지 못했습니다."}


def _config_facts(db: Session, run_id) -> list[tuple[SourceNode, list[dict[str, Any]]]]:
    """Worker가 파일 metadata의 config_facts에 남겨둔 설정 단서를 (파일, 단서 목록)으로 꺼낸다."""
    files = db.execute(
        select(SourceNode)
        .where(SourceNode.run_id == run_id, SourceNode.kind == "file", SourceNode.metadata_.has_key("config_facts"))
        .order_by(SourceNode.path.asc(), SourceNode.id.asc())
    ).scalars().all()
    result = []
    for file in files:
        facts = file.metadata_.get("config_facts")
        if isinstance(facts, list):
            result.append((file, [fact for fact in facts if isinstance(fact, dict)]))
    return result


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

    # architecture, erd: 최대 노드 수만 정리한다.
    return {"max_nodes": _int_option(options, "max_nodes", 150, 20, 300)}


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


def build_erd(db: Session, ready: ReadyRun, options: dict[str, Any]) -> Graph:
    """ERD: 표(table) → 칸(column)을 잇고, 외래 키(FK)는 칸 → 칸 화살표로 그린다."""
    run_id = ready.run.id
    max_nodes = options["max_nodes"]

    # ① 창고에서 재료 꺼내기: 표, 칸, 외래 키 (Worker가 .sql 파일에서 뽑아 저장해둔 것)
    tables = db.execute(
        select(SchemaTable)
        .where(SchemaTable.run_id == run_id)
        .order_by(SchemaTable.schema_name.asc(), SchemaTable.name.asc(), SchemaTable.id.asc())
    ).scalars().all()
    columns = db.execute(
        select(SchemaColumn)
        .where(SchemaColumn.run_id == run_id)
        .order_by(SchemaColumn.table_id.asc(), SchemaColumn.ordinal_position.asc(), SchemaColumn.id.asc())
    ).scalars().all()
    foreign_keys = db.execute(
        select(SchemaForeignKey)
        .where(SchemaForeignKey.run_id == run_id)
        .order_by(SchemaForeignKey.constraint_name.asc(), SchemaForeignKey.ordinal_position.asc(),
                  SchemaForeignKey.id.asc())
    ).scalars().all()

    # 표마다 어느 .sql 파일에서 나왔는지 (GitHub 링크를 만들기 위해)
    file_ids = {table.source_file_id for table in tables if table.source_file_id is not None}
    files = {}
    if file_ids:
        files = {
            node.id: node
            for node in db.execute(
                select(SourceNode).where(SourceNode.run_id == run_id, SourceNode.id.in_(file_ids))
            ).scalars()
        }

    columns_by_table = defaultdict(list)
    for column in columns:
        columns_by_table[column.table_id].append(column)

    graph = Graph()
    kept_columns: dict[int, SourceNode | None] = {}  # 그림에 들어간 칸 id → 그 표의 .sql 파일

    # ② 표 하나 + 그 표의 칸들을 한 묶음으로 넣는다. 묶음이 max_nodes를 넘기면 거기서 멈춘다.
    for table in tables:
        table_columns = columns_by_table[table.id]
        if len(graph.nodes) + 1 + len(table_columns) > max_nodes:
            graph.truncated = True
            graph.warnings.append(_truncation_warning(max_nodes))
            break

        file = files.get(table.source_file_id)
        label = table.name if table.schema_name == "public" else f"{table.schema_name}.{table.name}"
        graph.nodes.append(
            {
                "id": f"table:{table.id}",
                "type": "table",
                "label": label,
                "data": {
                    "schema": table.schema_name,
                    "name": table.name,
                    "path": file.path if file else None,
                    "github_url": ready.github_url(file.path, "file") if file else None,
                },
            }
        )
        for column in table_columns:
            graph.nodes.append(
                {
                    "id": f"column:{column.id}",
                    "type": "column",
                    "label": column.name,
                    "data": {
                        "data_type": column.data_type,
                        "is_primary": column.is_primary,
                        "is_nullable": column.is_nullable,
                        "ordinal_position": column.ordinal_position,
                    },
                }
            )
            # 표 → 칸 연결 (다른 그림들처럼 "contains")
            graph.edges.append(
                {
                    "id": f"contains:table:{table.id}:column:{column.id}",
                    "source": f"table:{table.id}",
                    "target": f"column:{column.id}",
                    "type": "contains",
                    "data": {},
                }
            )
            kept_columns[column.id] = file

    # ③ 외래 키 화살표: 두 칸이 모두 그림에 있을 때만 그린다.
    for fk in foreign_keys:
        if fk.source_column_id not in kept_columns:
            continue
        if fk.target_column_id is None:
            # 가리키는 표·칸을 .sql 안에서 못 찾은 FK (다른 파일, 오타 등)
            graph.unresolved_references += 1
            continue
        if fk.target_column_id not in kept_columns:
            continue  # max_nodes로 잘려서 대상 칸이 그림에 없음
        file = kept_columns[fk.source_column_id]
        graph.edges.append(
            {
                "id": f"foreign_key:{fk.id}",
                "source": f"column:{fk.source_column_id}",
                "target": f"column:{fk.target_column_id}",
                "type": "foreign_key",
                "data": {
                    "certainty": "confirmed",
                    "constraint_name": fk.constraint_name,
                    "ordinal_position": fk.ordinal_position,
                    "target_ref": fk.target_ref,
                    "evidence": [
                        {
                            "path": file.path if file else None,
                            "basis": "sql_ddl",
                            "github_url": ready.github_url(file.path, "file") if file else None,
                        }
                    ],
                },
            }
        )

    if graph.unresolved_references:
        graph.warnings.append(f"대상을 찾지 못한 외래 키 {graph.unresolved_references}개는 표시하지 않았습니다.")
    return graph


def _folder_label(ready: ReadyRun, path: str) -> str:
    """'frontend/package.json' → 'frontend', 루트에 있으면 저장소 이름."""
    parent = str(PurePosixPath(path).parent)
    return ready.repo.name if parent == "." else parent


def build_architecture(db: Session, ready: ReadyRun, options: dict[str, Any]) -> Graph:
    """architecture: 설정 파일 단서로 구성 요소(component)와 그 사이 연결을 그린다.

    - docker-compose services → 구성 요소, depends_on → 연결선(확실함, confirmed)
    - package.json / Dockerfile / FastAPI 앱 → 구성 요소 (연결선은 만들지 않는다)
    폴더 이름만 보고 "서로 연결돼 있다"고 짐작하지 않는다.
    """
    max_nodes = options["max_nodes"]
    graph = Graph()
    seen: set[str] = set()

    def add_node(node: dict[str, Any]) -> None:
        # 같은 구성 요소는 한 번만, 그리고 max_nodes까지만 넣는다.
        if node["id"] in seen:
            return
        if len(graph.nodes) >= max_nodes:
            graph.truncated = True
            return
        seen.add(node["id"])
        graph.nodes.append(node)

    def evidence(file: SourceNode, line: int | None = None) -> dict[str, Any]:
        # 연결·구성 요소의 근거 = 어느 설정 파일 몇 번째 줄에서 봤는지
        return {"path": file.path, "line": line, "basis": "config_file",
                "github_url": ready.github_url(file.path, "file", line, line)}

    facts_by_file = _config_facts(db, ready.run.id)
    dependencies = []  # (파일, 출발 서비스, 도착 서비스) — 노드를 다 넣은 뒤 선을 긋는다

    # ① 구성 요소 노드 만들기
    for file, facts in facts_by_file:
        routers = sum(1 for fact in facts if fact.get("kind") == "fastapi_router")
        frameworks = sorted(str(f["name"]) for f in facts if f.get("kind") == "framework" and "name" in f)
        scripts = sorted(str(f["name"]) for f in facts if f.get("kind") == "script" and "name" in f)

        for fact in facts:
            kind = fact.get("kind")
            if kind == "service" and isinstance(fact.get("name"), str):
                # docker-compose 서비스 하나 = 구성 요소 하나 (예: backend, db, frontend)
                add_node({"id": f"service:{fact['name']}", "type": "component", "label": fact["name"],
                          "data": {"kind": "service", "certainty": "confirmed", "path": file.path,
                                   "github_url": ready.github_url(file.path, "file"),
                                   "evidence": [evidence(file)]}})
            elif kind == "depends_on":
                dependencies.append((file, fact.get("source"), fact.get("target")))
            elif kind == "fastapi_app":
                # FastAPI()를 만드는 파일 = 백엔드 서버 진입점
                line = fact.get("line") if isinstance(fact.get("line"), int) else None
                add_node({"id": f"fastapi:{file.id}", "type": "component", "label": f"FastAPI · {file.path}",
                          "data": {"kind": "fastapi_app", "certainty": "confirmed", "path": file.path,
                                   "router_count": routers,
                                   "github_url": ready.github_url(file.path, "file", line, line),
                                   "evidence": [evidence(file, line)]}})
            elif kind == "dockerfile":
                add_node({"id": f"dockerfile:{file.id}", "type": "component",
                          "label": f"Dockerfile · {_folder_label(ready, file.path)}",
                          "data": {"kind": "dockerfile", "certainty": "confirmed", "path": file.path,
                                   "github_url": ready.github_url(file.path, "file"),
                                   "evidence": [evidence(file)]}})

        if PurePosixPath(file.path).name == "package.json" and (frameworks or scripts):
            # package.json 하나 = 자바스크립트 앱 하나 (예: frontend)
            add_node({"id": f"package:{file.id}", "type": "component", "label": _folder_label(ready, file.path),
                      "data": {"kind": "package", "certainty": "confirmed", "path": file.path,
                               "frameworks": frameworks, "scripts": scripts,
                               "github_url": ready.github_url(file.path, "file"),
                               "evidence": [evidence(file)]}})

    # ② 연결선: docker-compose의 depends_on만 (둘 다 그림에 있을 때)
    for file, source, target in dependencies:
        source_id, target_id = f"service:{source}", f"service:{target}"
        if source_id not in seen or target_id not in seen:
            continue
        graph.edges.append({"id": f"depends_on:{source}:{target}", "source": source_id, "target": target_id,
                            "type": "architecture_dependency",
                            "data": {"certainty": "confirmed", "evidence": [evidence(file)]}})

    if graph.truncated:
        graph.warnings.append(_truncation_warning(max_nodes))
    if not dependencies:
        graph.warnings.append("docker-compose의 depends_on이 없어 구성 요소 사이 연결은 표시하지 않았습니다.")
    return graph


BUILDERS = {
    "directory": build_directory,
    "dependency": build_dependency,
    "symbols": build_symbols,
    "architecture": build_architecture,
    "erd": build_erd,
}


def build_graph(db: Session, ready: ReadyRun, diagram_type: str, options: dict[str, Any]) -> Graph:
    graph = BUILDERS[diagram_type](db, ready, options)
    # 부분 분석(partial)일 때의 경고도 함께 보여준다.
    graph.warnings = [*(ready.run.warnings or []), *graph.warnings]
    return graph
