"""Build a reproducible metadata snapshot from a pinned GitHub archive."""

import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from worker.archive import ArchiveLimits, IndexedNode, index_archive
from worker.entities import Reference, SchemaTableFact, Symbol
from worker.github import GitHubClient, LimitExceeded, RepositoryAddress
from worker.parsers.config_facts import parse_config, parse_python_facts
from worker.parsers.javascript_ts import parse_javascript
from worker.parsers.python_ast import parse_python
from worker.parsers.sql_ddl import parse_sql
from worker.resolvers.imports import resolve_references

Progress = Callable[[str, int], None]


def analyze_archive(path: Path, repo: RepositoryAddress, sha: str, limits: ArchiveLimits,
                    *, deadline: float | None = None, progress: Progress | None = None) -> dict:
    nodes, warnings = index_archive(path, repo.name, limits, deadline)
    if progress:
        progress("parsing", 30)
    symbols: list[Symbol] = []
    references: list[Reference] = []
    tables: dict[tuple[str, str], SchemaTableFact] = {}
    conflicts: set[tuple[str, str]] = set()
    for node in nodes:
        if deadline is not None and time.monotonic() >= deadline:
            raise LimitExceeded("Analysis time limit exceeded")
        if node.kind != "file" or node.content is None:
            continue
        try:
            if node.language in {"python", "javascript", "typescript"}:
                parser = parse_python if node.language == "python" else parse_javascript
                found_symbols, found_refs, found_warnings = parser(node.path, node.content)
                symbols.extend(found_symbols)
                references.extend(found_refs)
                warnings.extend(found_warnings)
                node.parse_status = "failed" if found_warnings else "parsed"
                if node.language == "python" and not found_warnings:
                    facts = parse_python_facts(node.path, node.content)
                    if facts:
                        node.metadata["config_facts"] = facts
            elif node.language == "sql":
                found_tables, found_warnings = parse_sql(node.path, node.content)
                warnings.extend(found_warnings)
                node.parse_status = "failed" if any("parse error" in item for item in found_warnings) else "parsed"
                for table in found_tables:
                    key = table.schema_name, table.name
                    if key in tables or key in conflicts:
                        tables.pop(key, None)
                        if key not in conflicts:
                            warnings.append(f"Conflicting table declarations excluded: {table.schema_name}.{table.name}")
                        conflicts.add(key)
                    else:
                        tables[key] = table
            else:
                facts, found_warnings = parse_config(node.path, node.content)
                warnings.extend(found_warnings)
                if facts:
                    node.metadata["config_facts"] = facts
        except (ValueError, TypeError, RuntimeError, RecursionError):
            node.parse_status = "failed"
            warnings.append(f"Unable to analyze file: {node.path}")
        finally:
            node.content = None
    if progress:
        progress("resolving", 75)
    resolve_references(references, {node.path for node in nodes if node.kind == "file"})
    for table in tables.values():
        for fk in table.foreign_keys:
            target = tables.get((fk.target_schema, fk.target_table))
            if target is None or fk.target_column is None or fk.target_column not in {c.name for c in target.columns}:
                warnings.append(f"Unresolved foreign key: {table.schema_name}.{table.name}.{fk.source_column}")
    unresolved = sum(ref.resolution_status == "unresolved" for ref in references)
    unsupported = sum(node.parse_status == "unsupported" for node in nodes)
    if unresolved:
        warnings.append(f"Unresolved or dynamic imports: {unresolved}")
    if unsupported:
        warnings.append(f"Unsupported source files were indexed but not parsed: {unsupported}")
    warnings = list(dict.fromkeys(warnings))
    stats = {
        "file_count": sum(node.kind == "file" for node in nodes),
        "directory_count": sum(node.kind == "directory" for node in nodes),
        "parsed_files": sum(node.parse_status == "parsed" for node in nodes),
        "symbols": len(symbols),
        "resolved_imports": sum(ref.resolution_status == "resolved" for ref in references),
        "unresolved_imports": unresolved,
        "external_imports": sum(ref.resolution_status == "external" for ref in references),
        "tables": len(tables),
    }
    return {
        "repository_url": repo.url, "commit_sha": sha, "status": "partial" if warnings else "completed",
        "stats": stats, "warnings": warnings,
        "source_nodes": [_public_node(node) for node in nodes],
        "code_symbols": [asdict(symbol) for symbol in symbols],
        "code_references": [asdict(ref) for ref in references],
        "schema_tables": [asdict(table) for table in tables.values()],
    }


def _public_node(node: IndexedNode) -> dict:
    return {"path": node.path, "parent_path": node.parent_path, "name": node.name, "kind": node.kind,
            "language": node.language, "parse_status": node.parse_status, "metadata": node.metadata}


def analyze_repository(repo: RepositoryAddress, sha: str, limits: ArchiveLimits,
                       *, progress: Progress | None = None) -> dict:
    deadline = time.monotonic() + limits.timeout_seconds
    github = GitHubClient()
    try:
        with tempfile.TemporaryDirectory(prefix="repoatlas-") as tmp:
            archive = Path(tmp) / "snapshot.zip"
            if progress:
                progress("fetching", 5)
            github.download_archive(repo, sha, archive, max_bytes=limits.max_archive_bytes, deadline=deadline)
            return analyze_archive(archive, repo, sha, limits, deadline=deadline, progress=progress)
    finally:
        github.close()
