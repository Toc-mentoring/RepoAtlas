"""분석 결과 조회(A07~A09)와 다이어그램(A10~A12) API를 실제 PostgreSQL로 검사한다.

Worker가 저장했을 법한 작은 분석 결과를 직접 넣고 확인한다 (TEST_DATABASE_URL 필요).
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.models import AnalysisRun, CodeReference, CodeSymbol, Repository, SourceNode

SHA = "0123456789abcdef0123456789abcdef01234567"
BLOB = f"https://github.com/example-org/sample-web/blob/{SHA}"


@pytest.fixture
def seeded(api):
    """sample-web 저장소의 완료된 분석 결과 하나를 만든다.

    .
    ├── README.md
    └── src
        ├── main.py   (main 함수, user.py import / os 외부 / missing 미해결)
        └── user.py   (UserService 클래스 > get 메서드)
    """
    with Session(api.engine) as db:
        repo = Repository(owner="example-org", name="sample-web",
                          canonical_url="https://github.com/example-org/sample-web", default_branch="main")
        db.add(repo)
        db.flush()
        run = AnalysisRun(repository_id=repo.id, commit_sha=SHA, status="completed", progress=100)
        db.add(run)
        db.flush()

        def node(parent, kind, name, path, language=None, parse_status="not_applicable"):
            item = SourceNode(run_id=run.id, parent_id=parent.id if parent else None, kind=kind, name=name,
                              path=path, language=language, parse_status=parse_status)
            db.add(item)
            db.flush()
            return item

        root = node(None, "directory", "sample-web", ".")
        readme = node(root, "file", "README.md", "README.md")
        src = node(root, "directory", "src", "src")
        main = node(src, "file", "main.py", "src/main.py", "python", "parsed")
        user = node(src, "file", "user.py", "src/user.py", "python", "parsed")

        main_fn = CodeSymbol(run_id=run.id, file_id=main.id, kind="function", name="main",
                             qualified_name="main", start_line=7, end_line=15)
        service = CodeSymbol(run_id=run.id, file_id=user.id, kind="class", name="UserService",
                             qualified_name="UserService", start_line=1, end_line=20)
        db.add_all([main_fn, service])
        db.flush()
        get = CodeSymbol(run_id=run.id, file_id=user.id, parent_symbol_id=service.id, kind="method", name="get",
                         qualified_name="UserService.get", start_line=5, end_line=8)
        db.add(get)
        db.add_all([
            CodeReference(run_id=run.id, source_file_id=main.id, target_file_id=user.id, raw_ref="user",
                          source_line=3, resolution_status="resolved"),
            CodeReference(run_id=run.id, source_file_id=main.id, target_file_id=None, raw_ref="os",
                          source_line=1, resolution_status="external"),
            CodeReference(run_id=run.id, source_file_id=main.id, target_file_id=None, raw_ref="missing",
                          source_line=2, resolution_status="unresolved"),
        ])
        db.commit()
        ids = SimpleNamespace(run=str(run.id), root=root.id, readme=readme.id, src=src.id, main=main.id,
                              user=user.id, main_fn=main_fn.id, service=service.id, get=get.id)
    return SimpleNamespace(client=api.client, engine=api.engine, ids=ids)


def set_status(seeded, status):
    with seeded.engine.begin() as connection:
        connection.execute(text("UPDATE analysis_runs SET status = :s WHERE id = :id"), {"s": status, "id": seeded.ids.run})


def paths(response):
    return [item["path"] for item in response.json()["items"]]


# ------------------------------------------------------------------ A07 nodes


def test_nodes_default_depth_from_root(seeded):
    response = seeded.client.get(f"/api/v1/analyses/{seeded.ids.run}/nodes")
    assert response.status_code == 200
    assert paths(response) == [".", "README.md", "src", "src/main.py", "src/user.py"]
    root = response.json()["items"][0]
    assert root["name"] == "sample-web"
    assert root["parent_id"] is None
    assert response.json()["next_cursor"] is None


def test_nodes_depth_and_root_path(seeded):
    url = f"/api/v1/analyses/{seeded.ids.run}/nodes"
    assert paths(seeded.client.get(url, params={"depth": 1})) == [".", "README.md", "src"]
    assert paths(seeded.client.get(url, params={"root_path": "src"})) == ["src", "src/main.py", "src/user.py"]


def test_nodes_pagination(seeded):
    url = f"/api/v1/analyses/{seeded.ids.run}/nodes"
    first = seeded.client.get(url, params={"limit": 2}).json()
    second = seeded.client.get(url, params={"limit": 2, "cursor": first["next_cursor"]}).json()
    third = seeded.client.get(url, params={"limit": 2, "cursor": second["next_cursor"]}).json()
    collected = [item["path"] for page in (first, second, third) for item in page["items"]]
    assert collected == [".", "README.md", "src", "src/main.py", "src/user.py"]
    assert third["next_cursor"] is None


def test_nodes_errors(seeded):
    url = f"/api/v1/analyses/{seeded.ids.run}/nodes"
    assert seeded.client.get(url, params={"root_path": "nope"}).status_code == 404
    bad_root = seeded.client.get(url, params={"root_path": "../etc"})
    assert bad_root.status_code == 422
    assert bad_root.json()["error"]["code"] == "INVALID_FILTER"
    assert seeded.client.get(url, params={"depth": 9}).json()["error"]["code"] == "INVALID_FILTER"
    assert seeded.client.get(url, params={"cursor": "garbage!"}).status_code == 422
    assert seeded.client.get(f"/api/v1/analyses/{uuid4()}/nodes").json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


@pytest.mark.parametrize("status", ["queued", "parsing", "failed"])
def test_results_not_ready(seeded, status):
    set_status(seeded, status)
    response = seeded.client.get(f"/api/v1/analyses/{seeded.ids.run}/nodes")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_READY"


def test_partial_run_is_readable(seeded):
    set_status(seeded, "partial")
    assert seeded.client.get(f"/api/v1/analyses/{seeded.ids.run}/nodes").status_code == 200


# ------------------------------------------------------------------ A08 symbols


def test_symbols_all_and_github_url(seeded):
    response = seeded.client.get(f"/api/v1/analyses/{seeded.ids.run}/symbols")
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["qualified_name"] for item in items] == ["main", "UserService", "UserService.get"]
    assert items[0]["github_url"] == f"{BLOB}/src/main.py#L7-L15"
    assert items[2]["parent_symbol_id"] == seeded.ids.service


def test_symbols_filters(seeded):
    url = f"/api/v1/analyses/{seeded.ids.run}/symbols"
    methods = seeded.client.get(url, params={"file_id": seeded.ids.user, "kind": "method"}).json()["items"]
    assert [item["name"] for item in methods] == ["get"]

    bad_kind = seeded.client.get(url, params={"kind": "variable"})
    assert bad_kind.status_code == 422
    assert bad_kind.json()["error"]["code"] == "INVALID_FILTER"

    assert seeded.client.get(url, params={"file_id": seeded.ids.src}).status_code == 404
    assert seeded.client.get(url, params={"file_id": 999999}).status_code == 404


# ------------------------------------------------------------------ A09 search


def test_search_files_and_symbols(seeded):
    url = f"/api/v1/analyses/{seeded.ids.run}/search"
    items = seeded.client.get(url, params={"q": "user"}).json()["items"]
    assert items == [
        {"kind": "file", "id": f"file:{seeded.ids.user}", "label": "src/user.py", "path": "src/user.py", "line": None},
        {"kind": "symbol", "id": f"symbol:{seeded.ids.service}", "label": "UserService", "path": "src/user.py", "line": 1},
        {"kind": "symbol", "id": f"symbol:{seeded.ids.get}", "label": "UserService.get", "path": "src/user.py", "line": 5},
    ]
    only_files = seeded.client.get(url, params={"q": "user", "kind": "file"}).json()["items"]
    assert [item["id"] for item in only_files] == [f"file:{seeded.ids.user}"]
    assert seeded.client.get(url, params={"q": "u"}).status_code == 422


# ------------------------------------------------------------------ A10 diagram types


def test_diagram_types(seeded):
    response = seeded.client.get(f"/api/v1/analyses/{seeded.ids.run}/diagram-types")
    assert response.status_code == 200
    items = {item["type"]: item for item in response.json()["items"]}
    assert items["directory"]["availability"] == "available"
    assert items["dependency"]["availability"] == "available"
    assert items["symbols"]["availability"] == "available"
    assert items["architecture"]["availability"] == "unsupported"
    assert items["erd"] == {"type": "erd", "availability": "unsupported", "reason": "해석 가능한 SQL DDL 없음"}


# ------------------------------------------------------------------ A11 / A12 diagrams


def create(seeded, body):
    return seeded.client.post(f"/api/v1/analyses/{seeded.ids.run}/diagrams", json=body)


def test_directory_diagram_and_cache(seeded):
    created = create(seeded, {"type": "directory"})
    assert created.status_code == 201
    graph = created.json()
    assert graph["type"] == "directory"
    assert graph["availability"] == "available"
    assert graph["truncated"] is False
    assert [node["id"] for node in graph["nodes"]] == [
        f"dir:{seeded.ids.root}", f"file:{seeded.ids.readme}", f"dir:{seeded.ids.src}",
        f"file:{seeded.ids.main}", f"file:{seeded.ids.user}",
    ]
    assert {(edge["source"], edge["target"]) for edge in graph["edges"]} == {
        (f"dir:{seeded.ids.root}", f"file:{seeded.ids.readme}"),
        (f"dir:{seeded.ids.root}", f"dir:{seeded.ids.src}"),
        (f"dir:{seeded.ids.src}", f"file:{seeded.ids.main}"),
        (f"dir:{seeded.ids.src}", f"file:{seeded.ids.user}"),
    }

    # 같은 뜻의 옵션(기본값을 직접 적은 경우)은 캐시 적중
    again = create(seeded, {"type": "directory", "options": {"root_path": ".", "depth": 2, "max_nodes": 150}})
    assert again.status_code == 200
    assert again.json()["diagram_id"] == graph["diagram_id"]

    fetched = seeded.client.get(f"/api/v1/diagrams/{graph['diagram_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["nodes"] == graph["nodes"]
    assert fetched.json()["edges"] == graph["edges"]


def test_dependency_diagram(seeded):
    graph = create(seeded, {"type": "dependency"}).json()
    assert [node["id"] for node in graph["nodes"]] == [f"file:{seeded.ids.main}", f"file:{seeded.ids.user}"]
    assert graph["edges"] == [{
        "id": f"imports:{seeded.ids.main}:{seeded.ids.user}:3",
        "source": f"file:{seeded.ids.main}",
        "target": f"file:{seeded.ids.user}",
        "type": "imports",
        "data": {
            "certainty": "confirmed",
            "evidence": [{"path": "src/main.py", "line": 3, "basis": "python_ast_import",
                          "github_url": f"{BLOB}/src/main.py#L3"}],
        },
    }]
    assert graph["unresolved_references"] == 1
    assert graph["nodes"][0]["data"]["github_url"] == f"{BLOB}/src/main.py"


def test_symbols_diagram(seeded):
    missing = create(seeded, {"type": "symbols"})
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "INVALID_FILTER"

    graph = create(seeded, {"type": "symbols", "options": {"file_id": seeded.ids.user}}).json()
    assert [node["id"] for node in graph["nodes"]] == [
        f"file:{seeded.ids.user}", f"symbol:{seeded.ids.service}", f"symbol:{seeded.ids.get}",
    ]
    assert {(edge["source"], edge["target"]) for edge in graph["edges"]} == {
        (f"file:{seeded.ids.user}", f"symbol:{seeded.ids.service}"),
        (f"symbol:{seeded.ids.service}", f"symbol:{seeded.ids.get}"),
    }


def test_diagram_errors(seeded):
    unsupported = create(seeded, {"type": "erd"})
    assert unsupported.status_code == 409
    assert unsupported.json()["error"]["code"] == "DIAGRAM_UNSUPPORTED"

    assert create(seeded, {"type": "directory", "options": {"color": "red"}}).status_code == 422
    assert create(seeded, {"type": "directory", "options": {"max_nodes": 5}}).status_code == 422
    assert create(seeded, {"type": "directory", "options": {"root_path": "nope"}}).status_code == 422
    assert create(seeded, {"type": "graph"}).status_code == 422

    missing = seeded.client.get(f"/api/v1/diagrams/{uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "DIAGRAM_NOT_FOUND"

    set_status(seeded, "queued")
    assert create(seeded, {"type": "directory"}).json()["error"]["code"] == "ANALYSIS_NOT_READY"
