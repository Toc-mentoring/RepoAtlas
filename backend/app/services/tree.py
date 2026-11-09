"""폴더·파일 트리에서 '이 폴더 아래, 몇 단계까지'를 고르는 조건."""

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiError
from backend.app.models import SourceNode


def slash_count(column):
    return func.length(column) - func.length(func.replace(column, "/", ""))


def validate_root_path(root_path: str) -> str:
    root = root_path.strip().strip("/") or "."
    parts = root.split("/")
    if root != "." and any(part in ("", ".", "..") for part in parts):
        raise ApiError(422, "INVALID_FILTER", "root_path가 올바르지 않습니다.", {"root_path": root_path})
    return root


def get_root_node(db: Session, run_id, root_path: str, *, not_found_status: int = 404) -> SourceNode:
    root = validate_root_path(root_path)
    node = (
        db.query(SourceNode)
        .filter(SourceNode.run_id == run_id, SourceNode.path == root)
        .one_or_none()
    )
    if node is None or node.kind != "directory":
        raise ApiError(
            not_found_status,
            "INVALID_FILTER" if not_found_status == 422 else "NODE_NOT_FOUND",
            "root_path 폴더를 찾을 수 없습니다.",
            {"root_path": root_path},
        )
    return node


def within(root: SourceNode, depth: int):
    """root 자신 + root 아래 depth 단계까지의 노드 조건."""
    if root.path == ".":
        return or_(SourceNode.path == ".", slash_count(SourceNode.path) <= depth - 1)
    base = root.path.count("/")
    return or_(
        SourceNode.path == root.path,
        and_(
            SourceNode.path.startswith(root.path + "/", autoescape=True),
            slash_count(SourceNode.path) <= base + depth,
        ),
    )


def under(root: SourceNode):
    """root 아래 모든 노드 조건 (깊이 제한 없음)."""
    if root.path == ".":
        return SourceNode.path != "."
    return SourceNode.path.startswith(root.path + "/", autoescape=True)
