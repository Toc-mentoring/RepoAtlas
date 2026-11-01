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


@dataclass
class SchemaColumnFact:
    name: str
    data_type: str
    ordinal_position: int
    is_primary: bool
    is_nullable: bool


@dataclass
class SchemaForeignKeyFact:
    source_column: str
    constraint_name: str
    ordinal_position: int
    target_schema: str
    target_table: str
    target_column: str | None
    target_ref: str


@dataclass
class SchemaTableFact:
    source_path: str
    schema_name: str
    name: str
    columns: list[SchemaColumnFact]
    foreign_keys: list[SchemaForeignKeyFact]
