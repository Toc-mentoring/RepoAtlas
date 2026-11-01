"""Validate and index ZIP contents without extracting repository files."""

import os
import stat
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from worker.github import AnalysisError, LimitExceeded


@dataclass(frozen=True)
class ArchiveLimits:
    max_archive_bytes: int = 50 * 1024 * 1024
    max_extracted_bytes: int = 250 * 1024 * 1024
    max_files: int = 10_000
    max_source_file_bytes: int = 1024 * 1024
    timeout_seconds: int = 180

    @classmethod
    def from_environment(cls):
        defaults = cls()
        values = {}
        for field_name, variable in (
            ("max_archive_bytes", "MAX_ARCHIVE_BYTES"), ("max_extracted_bytes", "MAX_EXTRACTED_BYTES"),
            ("max_files", "MAX_FILES"), ("max_source_file_bytes", "MAX_SOURCE_FILE_BYTES"),
            ("timeout_seconds", "ANALYSIS_TIMEOUT_SECONDS"),
        ):
            value = int(os.environ.get(variable, getattr(defaults, field_name)))
            if value <= 0:
                raise ValueError(f"{variable} must be positive")
            values[field_name] = value
        return cls(**values)


@dataclass
class IndexedNode:
    path: str
    parent_path: str | None
    name: str
    kind: str
    language: str | None = None
    parse_status: str = "not_applicable"
    metadata: dict = field(default_factory=dict)
    archive_entry: str | None = field(default=None, repr=False)


_LANGUAGES = {".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
              ".cjs": "javascript", ".ts": "typescript", ".tsx": "typescript", ".sql": "sql"}
_UNSUPPORTED = {".java", ".c", ".h", ".cc", ".cpp", ".hpp", ".go", ".rs", ".rb", ".php", ".swift"}
_CONFIG_NAMES = {"package.json", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml", "Dockerfile"}


def index_archive(archive_path: Path, repo_name: str, limits: ArchiveLimits,
                  deadline: float | None = None) -> tuple[list[IndexedNode], list[str]]:
    if archive_path.stat().st_size > limits.max_archive_bytes:
        raise LimitExceeded("Archive exceeds the download size limit")
    nodes = {".": IndexedNode(".", None, repo_name, "directory")}
    warnings = []
    root = None
    paths = set()
    file_count = 0
    total_size = 0
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            if len(entries) > limits.max_files * 2 + 1:
                raise LimitExceeded("Archive has too many entries")
            for entry in entries:
                if deadline is not None and time.monotonic() >= deadline:
                    raise LimitExceeded("Analysis time limit exceeded")
                name = entry.orig_filename
                components = name.rstrip("/").split("/")
                if (not name or len(name) > 4096 or name.startswith("/") or "\\" in name or "\x00" in name or
                        any(part in {"", ".", ".."} for part in components) or
                        any(":" in part for part in components) or entry.flag_bits & 1):
                    raise AnalysisError("UNSAFE_ARCHIVE", "Archive contains an unsafe path or encrypted entry")
                mode = entry.external_attr >> 16
                is_symlink = entry.create_system == 3 and stat.S_ISLNK(mode)
                if is_symlink and entry.is_dir():
                    raise AnalysisError("UNSAFE_ARCHIVE", "Archive contains a malformed symbolic link")
                if root is None:
                    root = components[0]
                if components[0] != root:
                    raise AnalysisError("UNSAFE_ARCHIVE", "Archive must have one common root directory")
                relative = "/".join(components[1:])
                if not relative:
                    if not entry.is_dir():
                        raise AnalysisError("UNSAFE_ARCHIVE", "Archive root must be a directory")
                    continue
                if relative in paths:
                    raise AnalysisError("UNSAFE_ARCHIVE", "Archive contains duplicate paths")
                paths.add(relative)
                if not entry.is_dir():
                    file_count += 1
                    total_size += entry.file_size
                    if file_count > limits.max_files or total_size > limits.max_extracted_bytes:
                        raise LimitExceeded("Archive exceeds the file count or extracted size limit")
                    if entry.file_size > 1_000_000 and entry.file_size > max(entry.compress_size, 1) * 200:
                        raise LimitExceeded("Archive entry has an unsafe compression ratio")
                parts = relative.split("/")
                for index in range(1, len(parts)):
                    directory = "/".join(parts[:index])
                    parent = "/".join(parts[:index - 1]) or "."
                    if directory in nodes and nodes[directory].kind != "directory":
                        raise AnalysisError("UNSAFE_ARCHIVE", "Archive contains conflicting file and directory paths")
                    nodes.setdefault(directory, IndexedNode(directory, parent, parts[index - 1], "directory"))
                parent = "/".join(parts[:-1]) or "."
                if entry.is_dir():
                    if relative in nodes and nodes[relative].kind != "directory":
                        raise AnalysisError("UNSAFE_ARCHIVE", "Archive contains conflicting file and directory paths")
                    nodes.setdefault(relative, IndexedNode(relative, parent, parts[-1], "directory"))
                    continue
                if relative in nodes:
                    raise AnalysisError("UNSAFE_ARCHIVE", "Archive contains conflicting file and directory paths")
                suffix = PurePosixPath(relative).suffix.lower()
                language = _LANGUAGES.get(suffix)
                status = "unsupported" if suffix in _UNSUPPORTED else "not_applicable"
                node = IndexedNode(relative, parent, parts[-1], "file", language, status,
                                   {"size_bytes": entry.file_size})
                if is_symlink:
                    node.parse_status = "skipped"
                    node.metadata["is_symlink"] = True
                    warnings.append(f"Symbolic link was not followed: {relative}")
                elif language or parts[-1] in _CONFIG_NAMES:
                    if entry.file_size > limits.max_source_file_bytes:
                        node.parse_status = "skipped"
                        warnings.append(f"File exceeds analysis size limit: {relative}")
                    else:
                        node.archive_entry = entry.filename
                if parts[-1] == ".gitmodules":
                    warnings.append("Git submodule contents are not included in GitHub archives")
                nodes[relative] = node
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise AnalysisError("INVALID_ARCHIVE", "GitHub archive could not be read safely") from exc
    return sorted(nodes.values(), key=lambda node: (node.path.count("/"), node.path != ".", node.path)), warnings
