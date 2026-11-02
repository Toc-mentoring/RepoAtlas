"""Extract Python declarations and import statements without executing code."""

import ast

from worker.entities import Reference, Symbol


def parse_python(path: str, content: bytes) -> tuple[list[Symbol], list[Reference], list[str]]:
    try:
        tree = ast.parse(content, filename=path)
    except (SyntaxError, UnicodeError, ValueError):
        return [], [], [f"Python syntax or encoding error: {path}"]

    symbols: list[Symbol] = []
    references: list[Reference] = []
    parents: list[Symbol] = []

    class Visitor(ast.NodeVisitor):
        def declaration(self, node, kind):
            parent = parents[-1] if parents else None
            qualified = f"{parent.qualified_name}.{node.name}" if parent else node.name
            symbol = Symbol(path, node.name, qualified, kind, node.lineno, node.end_lineno or node.lineno,
                            parent.qualified_name if parent else None, parent.start_line if parent else None,
                            node.col_offset, parent.start_column if parent else None)
            symbols.append(symbol)
            parents.append(symbol)
            self.generic_visit(node)
            parents.pop()

        def visit_ClassDef(self, node):
            self.declaration(node, "class")

        def visit_FunctionDef(self, node):
            self.declaration(node, "method" if parents and parents[-1].kind == "class" else "function")

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Import(self, node):
            for alias in node.names:
                references.append(Reference(path, alias.name, node.lineno, "python", module=alias.name))

        def visit_ImportFrom(self, node):
            module = node.module or ""
            for alias in node.names:
                raw = "." * node.level + (module or alias.name)
                references.append(Reference(path, raw, node.lineno, "python", module=module,
                                            member=alias.name, level=node.level))

        def visit_Call(self, node):
            dynamic = (isinstance(node.func, ast.Name) and node.func.id == "__import__") or (
                isinstance(node.func, ast.Attribute) and node.func.attr == "import_module" and
                isinstance(node.func.value, ast.Name) and node.func.value.id == "importlib"
            )
            if dynamic:
                name = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) else "<dynamic>"
                references.append(Reference(path, name, node.lineno, "python", mode="dynamic"))
            self.generic_visit(node)

    Visitor().visit(tree)
    return symbols, references, []
