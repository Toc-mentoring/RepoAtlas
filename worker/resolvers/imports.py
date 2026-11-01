"""Resolve imports only when a target file can be identified from the snapshot."""

import posixpath
import sys
from pathlib import PurePosixPath

from worker.entities import Reference


def _python_candidates(base: str, paths: set[str]) -> set[str]:
    candidates = (posixpath.normpath(base + ".py"), posixpath.normpath(base + "/__init__.py"))
    return {candidate for candidate in candidates if candidate in paths}


def _blocked_by_module(base: str, root: str, paths: set[str]) -> bool:
    parts = posixpath.relpath(base, root).split("/")
    prefix = root
    for part in parts[:-1]:
        prefix = posixpath.normpath(posixpath.join(prefix, part))
        if prefix + ".py" in paths and posixpath.join(prefix, "__init__.py") not in paths:
            return True
    return False


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
        roots = [(base, str(parent))]
    else:
        roots = [(module, "."), (posixpath.join("src", module), "src")] if module else []

    candidates = set()
    for base, root in roots:
        if _blocked_by_module(base, root, paths):
            continue
        base_candidates = _python_candidates(base, paths)
        module_file = posixpath.normpath(base + ".py")
        if ref.level and not ref.module:
            base_candidates.discard(module_file)
        candidates.update(base_candidates)
        if ref.member and ref.member != "*":
            # A plain module wins over a same-named directory. A package can
            # export an attribute or a submodule, so retain both candidates.
            if module_file not in base_candidates or len(base_candidates) > 1:
                candidates.update(_python_candidates(posixpath.join(base, ref.member), paths))
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
