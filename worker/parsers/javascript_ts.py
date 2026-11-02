"""Extract JavaScript and TypeScript declarations with Tree-sitter."""

from pathlib import PurePosixPath

from tree_sitter import Language, Parser
import tree_sitter_javascript
import tree_sitter_typescript

from worker.entities import Reference, Symbol


def parse_javascript(path: str, content: bytes) -> tuple[list[Symbol], list[Reference], list[str]]:
    suffix = PurePosixPath(path).suffix.lower()
    grammar = (tree_sitter_typescript.language_tsx() if suffix == ".tsx" else
               tree_sitter_typescript.language_typescript() if suffix == ".ts" else
               tree_sitter_javascript.language())
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return [], [], [f"JavaScript/TypeScript encoding error: {path}"]
    tree = Parser(Language(grammar)).parse(content)
    if tree.root_node.has_error:
        return [], [], [f"JavaScript/TypeScript syntax error: {path}"]

    symbols: list[Symbol] = []
    references: list[Reference] = []
    parents: list[Symbol] = []

    def text(node):
        return content[node.start_byte:node.end_byte].decode("utf-8")

    def string_value(node):
        if node is None or node.type != "string" or any(child.type == "escape_sequence" for child in node.named_children):
            return None
        return text(node)[1:-1]

    def visit(node):
        if node.type in ("import_statement", "export_statement"):
            source = node.child_by_field_name("source")
            if source is not None:
                value = string_value(source)
                raw = value if value is not None else text(source)[1:-1]
                references.append(Reference(path, raw, node.start_point.row + 1, "javascript"))
        elif node.type == "call_expression":
            function = node.child_by_field_name("function")
            arguments = node.child_by_field_name("arguments")
            if function is not None and text(function) in ("require", "import"):
                argument = arguments.named_children[0] if arguments and arguments.named_children else None
                value = string_value(argument)
                static_require = text(function) == "require" and argument is not None and argument.type == "string"
                raw = value if value is not None else text(argument)[1:-1] if static_require else "<dynamic>"
                references.append(Reference(path, raw, node.start_point.row + 1, "javascript",
                                            mode="static" if static_require else "dynamic"))

        kind = {"function_declaration": "function", "generator_function_declaration": "function",
                "class_declaration": "class", "interface_declaration": "interface"}.get(node.type)
        if node.type == "method_definition" and parents and parents[-1].kind in ("class", "interface"):
            kind = "method"
        if node.type == "variable_declarator":
            value = node.child_by_field_name("value")
            if value is not None and value.type in ("arrow_function", "function_expression", "generator_function"):
                kind = "function"
        name_node = node.child_by_field_name("name")
        anonymous = False
        if node.type in ("arrow_function", "function_expression", "generator_function"):
            parent_node = node.parent
            assigned_name = parent_node.child_by_field_name("name") if parent_node and parent_node.type == "variable_declarator" else None
            if assigned_name is None or assigned_name.type != "identifier":
                kind = "function"
                anonymous = name_node is None
        symbol = None
        if kind and (anonymous or name_node is not None and name_node.type in ("identifier", "type_identifier", "property_identifier", "private_property_identifier")):
            name = f"<anonymous@{node.start_point.row + 1}:{node.start_point.column}>" if anonymous else text(name_node)
            parent = parents[-1] if parents else None
            qualified = f"{parent.qualified_name}.{name}" if parent else name
            symbol = Symbol(path, name, qualified, kind, node.start_point.row + 1, node.end_point.row + 1,
                            parent.qualified_name if parent else None, parent.start_line if parent else None,
                            node.start_point.column, parent.start_column if parent else None)
            symbols.append(symbol)
            parents.append(symbol)
        for child in node.named_children:
            visit(child)
        if symbol is not None:
            parents.pop()

    visit(tree.root_node)
    return symbols, references, []
