"""Collect an allowlist of configuration facts without preserving secret values."""

import ast
import json
import re
from pathlib import PurePosixPath

import yaml

_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_FRAMEWORKS = {"react", "vite", "next", "vue", "angular", "express", "fastify", "typescript"}
_SCRIPT_NAMES = {"build", "dev", "start", "test"}


def parse_config(path: str, content: bytes) -> tuple[list[dict], list[str]]:
    name = PurePosixPath(path).name
    facts = []
    try:
        if name in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
            data = yaml.safe_load(content) or {}
            services = data.get("services", {}) if isinstance(data, dict) else {}
            if not isinstance(services, dict):
                raise ValueError("invalid services")
            for service, value in services.items():
                if not isinstance(service, str) or not _NAME.fullmatch(service):
                    continue
                facts.append({"kind": "service", "name": service, "certainty": "confirmed"})
                depends = value.get("depends_on", []) if isinstance(value, dict) else []
                if isinstance(depends, (list, dict)):
                    for dependency in depends:
                        if isinstance(dependency, str) and _NAME.fullmatch(dependency) and dependency in services:
                            facts.append({"kind": "depends_on", "source": service, "target": dependency,
                                          "certainty": "confirmed"})
        elif name == "package.json":
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError("invalid package")
            dependencies = set()
            for key in ("dependencies", "devDependencies", "peerDependencies"):
                value = data.get(key, {})
                if isinstance(value, dict):
                    dependencies.update(value.keys())
            for dependency in sorted(_FRAMEWORKS & dependencies):
                facts.append({"kind": "framework", "name": dependency, "certainty": "confirmed"})
            scripts = data.get("scripts", {})
            if isinstance(scripts, dict):
                for script in sorted(_SCRIPT_NAMES & scripts.keys()):
                    facts.append({"kind": "script", "name": script, "certainty": "confirmed"})
        elif name == "Dockerfile":
            facts.append({"kind": "dockerfile", "certainty": "confirmed"})
    except (ValueError, TypeError, UnicodeDecodeError, yaml.YAMLError, RecursionError):
        return [], [f"Configuration parse error: {path}"]
    return facts, []


def parse_python_facts(path: str, content: bytes) -> list[dict]:
    try:
        tree = ast.parse(content, filename=path)
    except (SyntaxError, UnicodeError, ValueError):
        return []
    fastapi_names = set()
    fastapi_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "fastapi":
            fastapi_names.update(alias.asname or alias.name for alias in node.names if alias.name == "FastAPI")
        elif isinstance(node, ast.Import):
            fastapi_modules.update(alias.asname or alias.name for alias in node.names if alias.name == "fastapi")
    facts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            direct_app = isinstance(node.func, ast.Name) and node.func.id in fastapi_names
            module_app = (isinstance(node.func, ast.Attribute) and node.func.attr == "FastAPI" and
                          isinstance(node.func.value, ast.Name) and node.func.value.id in fastapi_modules)
            if direct_app or module_app:
                facts.append({"kind": "fastapi_app", "line": node.lineno, "certainty": "confirmed"})
            elif isinstance(node.func, ast.Attribute) and node.func.attr == "include_router":
                facts.append({"kind": "fastapi_router", "line": node.lineno, "certainty": "inferred"})
    return facts
