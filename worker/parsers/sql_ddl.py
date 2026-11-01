"""Extract static PostgreSQL CREATE TABLE facts without executing SQL."""

import sqlglot
from sqlglot import exp

from worker.entities import SchemaColumnFact, SchemaForeignKeyFact, SchemaTableFact


def parse_sql(path: str, content: bytes) -> tuple[list[SchemaTableFact], list[str]]:
    try:
        statements = sqlglot.parse(content.decode("utf-8"), read="postgres", error_level=sqlglot.ErrorLevel.RAISE)
    except (UnicodeDecodeError, sqlglot.errors.ParseError, ValueError, RecursionError):
        return [], [f"PostgreSQL DDL parse error: {path}"]
    tables = []
    warnings = []
    for statement in statements:
        if statement is None:
            continue
        if isinstance(statement, exp.Alter):
            warnings.append(f"ALTER TABLE is not applied to the static schema: {path}")
            continue
        if not isinstance(statement, exp.Create) or statement.args.get("kind") != "TABLE":
            continue
        schema = statement.this
        if not isinstance(schema, exp.Schema) or not isinstance(schema.this, exp.Table):
            warnings.append(f"CREATE TABLE without explicit columns is unsupported: {path}")
            continue
        table = schema.this
        table_name = table.name
        schema_name = table.db or "public"
        if not table_name:
            warnings.append(f"CREATE TABLE without a table name is unsupported: {path}")
            continue
        definitions = schema.expressions
        primary = set()
        for definition in definitions:
            constraints = definition.expressions if isinstance(definition, exp.Constraint) else [definition]
            for constraint in constraints:
                if isinstance(constraint, exp.PrimaryKey):
                    primary.update(column.name for column in constraint.expressions)
        columns = []
        pending_fks = []
        for definition in definitions:
            if isinstance(definition, exp.ColumnDef):
                name = definition.name
                datatype = definition.args.get("kind")
                if not name or datatype is None:
                    warnings.append(f"Column without a name or type is unsupported: {path}")
                    continue
                constraints = definition.args.get("constraints") or []
                is_primary = name in primary or any(isinstance(c.args.get("kind"), exp.PrimaryKeyColumnConstraint) for c in constraints)
                not_null = is_primary or any(isinstance(c.args.get("kind"), exp.NotNullColumnConstraint) for c in constraints)
                columns.append(SchemaColumnFact(name, datatype.sql(dialect="postgres"), len(columns) + 1, is_primary, not not_null))
                for constraint in constraints:
                    reference = constraint.args.get("kind")
                    if isinstance(reference, exp.Reference):
                        pending_fks.append((constraint.name or f"{table_name}_{name}_fkey", [name], reference))
            else:
                items = definition.expressions if isinstance(definition, exp.Constraint) else [definition]
                for item in items:
                    if isinstance(item, exp.ForeignKey):
                        sources = [column.name for column in item.expressions]
                        name = definition.name if isinstance(definition, exp.Constraint) else ""
                        pending_fks.append((name or f"{table_name}_{'_'.join(sources)}_fkey", sources, item.args.get("reference")))
        foreign_keys = []
        for constraint_name, sources, reference in pending_fks:
            target = reference.this if isinstance(reference, exp.Reference) else None
            target_table = target.this if isinstance(target, exp.Schema) else target
            if not isinstance(target_table, exp.Table) or not target_table.name:
                warnings.append(f"Foreign key target is unsupported: {path}")
                continue
            target_schema = target_table.db or "public"
            target_columns = [column.name for column in target.expressions] if isinstance(target, exp.Schema) else []
            if target_columns and len(target_columns) != len(sources):
                warnings.append(f"Foreign key column count is inconsistent: {path}")
                continue
            for index, source in enumerate(sources):
                target_column = target_columns[index] if target_columns else None
                target_ref = f"{target_schema}.{target_table.name}" + (f"({target_column})" if target_column else "")
                foreign_keys.append(SchemaForeignKeyFact(source, constraint_name, index + 1, target_schema,
                                                         target_table.name, target_column, target_ref))
        tables.append(SchemaTableFact(path, schema_name, table_name, columns, foreign_keys))
    return tables, warnings
