"""Analysis facts passed between parsers, the resolver and persistence."""

from dataclasses import dataclass


@dataclass
class Symbol:
    file_path: str
    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int
    parent_qualified_name: str | None = None
    parent_start_line: int | None = None


@dataclass
class Reference:
    source_path: str
    raw_ref: str
    source_line: int
    language: str
    mode: str = "static"
    module: str = ""
    member: str | None = None
    level: int = 0
    target_path: str | None = None
    resolution_status: str = "unresolved"
