"""Resolve imports only when a target file can be identified from the snapshot."""

import posixpath
import sys
from pathlib import PurePosixPath

from worker.entities import Reference


def _python_candidates(base: str, paths: set[str]) -> set[str]:
    candidates = (posixpath.normpath(base + ".py"), posixpath.normpath(base + "/__init__.py"))
    return {candidate for candidate in candidates if candidate in paths}


def _python_target(ref: Reference, paths: set[str]) -> tuple[str | None, str]:
    module = ref.module.replace(".", "/")
    if ref.level:
        parent = PurePosixPath(ref.source_path).parent
        for _ in range(ref.level - 1):
            if str(parent) == ".":
                return None, "unresolved"
            parent = parent.parent
        base = posixpath.normpath(posixpath.join(str(parent), module))
        if base == ".." or base.startswith("../"):
            return None, "unresolved"
        roots = [base]
    else:
        roots = [module, posixpath.join("src", module)] if module else []

    if ref.member and ref.member != "*":
        submodules = set()
        for base in roots:
            submodules.update(_python_candidates(posixpath.join(base, ref.member), paths))
        if len(submodules) == 1:
            return next(iter(submodules)), "resolved"
        if len(submodules) > 1:
            return None, "unresolved"
    candidates = set()
    for base in roots:
        candidates.update(_python_candidates(base, paths))
    if len(candidates) == 1:
        return next(iter(candidates)), "resolved"
    if len(candidates) > 1:
        return None, "unresolved"
    if not ref.level and ref.module.split(".", 1)[0] in sys.stdlib_module_names:
        return None, "external"
    return None, "unresolved"


def _javascript_target(ref: Reference, paths: set[str]) -> tuple[str | None, str]:
    raw = ref.raw_ref
    if not raw.startswith(("./", "../")):
        return None, "unresolved" if raw.startswith(("@/", "/", "#")) else "external"
    base = posixpath.normpath(posixpath.join(posixpath.dirname(ref.source_path), raw))
    if base == ".." or base.startswith("../") or base.startswith("/"):
        return None, "unresolved"
    if base in paths:
        return base, "resolved"
    for suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        candidate = base + suffix
        if candidate in paths:
            return candidate, "resolved"
    for suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        candidate = posixpath.join(base, "index" + suffix)
        if candidate in paths:
            return candidate, "resolved"
    return None, "unresolved"


def resolve_references(references: list[Reference], file_paths: set[str]) -> None:
    for ref in references:
        if ref.mode == "dynamic":
            continue
        if ref.language == "python":
            ref.target_path, ref.resolution_status = _python_target(ref, file_paths)
        else:
            ref.target_path, ref.resolution_status = _javascript_target(ref, file_paths)
