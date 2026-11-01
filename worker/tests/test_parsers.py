from worker.parsers.javascript_ts import parse_javascript
from worker.parsers.python_ast import parse_python
from worker.resolvers.imports import resolve_references


def test_python_symbols_imports_and_dynamic_imports():
    source = b'''import os
from . import helper
class Service:
    async def run(self):
        def inner():
            return __import__("dynamic_package")
        return inner()
'''
    symbols, references, warnings = parse_python("pkg/service.py", source)
    assert [(s.qualified_name, s.kind, s.start_line, s.parent_qualified_name) for s in symbols] == [
        ("Service", "class", 3, None), ("Service.run", "method", 4, "Service"),
        ("Service.run.inner", "function", 5, "Service.run"),
    ]
    resolve_references(references, {"pkg/service.py", "pkg/helper.py"})
    assert [(r.raw_ref, r.target_path, r.resolution_status) for r in references] == [
        ("os", None, "external"), (".helper", "pkg/helper.py", "resolved"),
        ("dynamic_package", None, "unresolved"),
    ]
    assert warnings == []


def test_javascript_and_typescript_declarations_and_references():
    source = b'''import React from 'react';
import { item } from './item';
export { value } from './value';
export interface User { name: string }
export class Api { get(): void {} }
export const run = () => require('./handler');
const dynamic = import('./lazy');
'''
    symbols, references, warnings = parse_javascript("src/app.ts", source)
    assert [(s.qualified_name, s.kind) for s in symbols] == [
        ("User", "interface"), ("Api", "class"), ("Api.get", "method"), ("run", "function"),
    ]
    resolve_references(references, {"src/app.ts", "src/item.ts", "src/value.ts", "src/handler.ts", "src/lazy.ts"})
    assert [(r.raw_ref, r.target_path, r.resolution_status) for r in references] == [
        ("react", None, "external"), ("./item", "src/item.ts", "resolved"),
        ("./value", "src/value.ts", "resolved"), ("./handler", "src/handler.ts", "resolved"),
        ("./lazy", None, "unresolved"),
    ]
    assert warnings == []


def test_syntax_errors_do_not_invent_facts():
    assert parse_python("bad.py", b"def broken(:\n")[0:2] == ([], [])
    assert parse_javascript("bad.ts", b"export const = ;")[0:2] == ([], [])
    assert parse_python("bad.py", b"def broken(:\n")[2]
    assert parse_javascript("bad.ts", b"export const = ;")[2]


def test_same_line_parent_declarations_remain_distinguishable():
    symbols, _, warnings = parse_javascript("same.js", b"function f(){function g(){}} function f(){function g(){}}")
    assert not warnings
    parents = [symbol for symbol in symbols if symbol.qualified_name == "f"]
    children = [symbol for symbol in symbols if symbol.qualified_name == "f.g"]
    assert len(parents) == len(children) == 2
    assert [child.parent_start_column for child in children] == [parent.start_column for parent in parents]
    assert parents[0].start_column != parents[1].start_column


def test_escaped_static_import_is_not_reported_as_dynamic():
    _, refs, warnings = parse_javascript("main.js", br"import './a\u0062';")
    resolve_references(refs, {"main.js", "ab.js"})
    assert not warnings
    assert refs[0].mode == "static" and refs[0].resolution_status == "unresolved"
