"""분석 결과 조회(A07~A09)와 다이어그램(A10~A12) API를 실제 PostgreSQL로 검사한다.

Worker가 저장했을 법한 작은 분석 결과를 직접 넣고 확인한다 (TEST_DATABASE_URL 필요).
"""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.models import (
    AnalysisRun,
    CodeReference,
    CodeSymbol,
    Repository,
    SchemaColumn,
    SchemaForeignKey,
    SchemaTable,
    SourceNode,
)

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


# ------------------------------------------------------------------ ERD / architecture


def add_file(seeded, path, metadata=None):
    """루트 폴더 아래에 파일 노드 하나를 추가한다 (metadata에 Worker가 남긴 설정 단서를 넣을 수 있다)."""
    with Session(seeded.engine) as db:
        node = SourceNode(run_id=UUID(seeded.ids.run), parent_id=seeded.ids.root, kind="file",
                          name=path.rsplit("/", 1)[-1], path=path, parse_status="parsed",
                          metadata_=metadata or {})
        db.add(node)
        db.commit()
        return node.id


def add_schema(seeded):
    """schema.sql: users(id PK, email), posts(id PK, user_id → users.id, editor_id → 못 찾은 표)"""
    sql_id = add_file(seeded, "schema.sql")
    run_id = UUID(seeded.ids.run)
    with Session(seeded.engine) as db:
        users = SchemaTable(run_id=run_id, name="users", source_file_id=sql_id)
        posts = SchemaTable(run_id=run_id, name="posts", source_file_id=sql_id)
        db.add_all([users, posts])
        db.flush()

        def column(table, name, position, primary=False):
            item = SchemaColumn(run_id=run_id, table_id=table.id, name=name, data_type="integer",
                                ordinal_position=position, is_primary=primary, is_nullable=not primary)
            db.add(item)
            db.flush()
            return item

        users_id = column(users, "id", 1, primary=True)
        column(users, "email", 2)
        column(posts, "id", 1, primary=True)
        posts_user = column(posts, "user_id", 2)
        posts_editor = column(posts, "editor_id", 3)
        db.add_all([
            SchemaForeignKey(run_id=run_id, source_column_id=posts_user.id, target_column_id=users_id.id,
                             constraint_name="posts_user_fk", ordinal_position=1, target_ref="users.id"),
            SchemaForeignKey(run_id=run_id, source_column_id=posts_editor.id, target_column_id=None,
                             constraint_name="posts_editor_fk", ordinal_position=1, target_ref="editors.id"),
        ])
        db.commit()
        return SimpleNamespace(users=users.id, posts=posts.id, users_id=users_id.id, posts_user=posts_user.id)


def test_erd_diagram(seeded):
    ids = add_schema(seeded)

    items = {item["type"]: item for item in seeded.client.get(f"/api/v1/analyses/{seeded.ids.run}/diagram-types").json()["items"]}
    assert items["erd"] == {"type": "erd", "availability": "available", "reason": None}

    created = create(seeded, {"type": "erd"})
    assert created.status_code == 201
    body = created.json()
    assert body["type"] == "erd"
    assert body["availability"] == "available"

    labels = {node["id"]: node["label"] for node in body["nodes"]}
    assert labels[f"table:{ids.users}"] == "users"
    assert labels[f"table:{ids.posts}"] == "posts"
    assert len(body["nodes"]) == 7  # 표 2개 + 칸 5개
    assert body["nodes"][0]["data"]["github_url"] == f"{BLOB}/schema.sql"

    fk = [edge for edge in body["edges"] if edge["type"] == "foreign_key"]
    assert len(fk) == 1
    assert fk[0]["source"] == f"column:{ids.posts_user}"
    assert fk[0]["target"] == f"column:{ids.users_id}"
    assert fk[0]["data"]["certainty"] == "confirmed"
    assert len([edge for edge in body["edges"] if edge["type"] == "contains"]) == 5

    # 대상을 못 찾은 FK(editors.id)는 선 대신 숫자와 경고로 알려준다.
    assert body["unresolved_references"] == 1
    assert any("외래 키" in warning for warning in body["warnings"])

    assert create(seeded, {"type": "erd"}).status_code == 200  # 같은 옵션이면 캐시
    assert create(seeded, {"type": "erd", "options": {"root_path": "."}}).status_code == 422


def test_erd_truncates_by_table(seeded):
    add_schema(seeded)
    # posts 묶음(표1+칸3=4) + users 묶음(표1+칸2=3) = 7개. 여기에 칸 19개짜리 표를 더하면 20개를 넘는다.
    run_id = UUID(seeded.ids.run)
    with Session(seeded.engine) as db:
        big = SchemaTable(run_id=run_id, name="zzz_big")
        db.add(big)
        db.flush()
        db.add_all([SchemaColumn(run_id=run_id, table_id=big.id, name=f"c{i}", data_type="text",
                                 ordinal_position=i) for i in range(1, 20)])
        db.commit()

    body = create(seeded, {"type": "erd", "options": {"max_nodes": 20}}).json()
    assert body["truncated"] is True
    assert len(body["nodes"]) == 7  # 20개를 넘기는 zzz_big 묶음은 통째로 빠진다
    assert not any(node["label"] == "zzz_big" for node in body["nodes"])


def test_architecture_from_compose(seeded):
    add_file(seeded, "docker-compose.yml", {"config_facts": [
        {"kind": "service", "name": "api", "certainty": "confirmed"},
        {"kind": "service", "name": "db", "certainty": "confirmed"},
        {"kind": "depends_on", "source": "api", "target": "db", "certainty": "confirmed"},
    ]})
    add_file(seeded, "frontend/package.json", {"config_facts": [
        {"kind": "framework", "name": "react", "certainty": "confirmed"},
        {"kind": "script", "name": "build", "certainty": "confirmed"},
    ]})

    items = {item["type"]: item for item in seeded.client.get(f"/api/v1/analyses/{seeded.ids.run}/diagram-types").json()["items"]}
    assert items["architecture"]["availability"] == "available"

    created = create(seeded, {"type": "architecture"})
    assert created.status_code == 201
    body = created.json()
    assert body["availability"] == "available"

    nodes = {node["id"]: node for node in body["nodes"]}
    assert set(nodes) >= {"service:api", "service:db"}
    package = next(node for node in body["nodes"] if node["data"]["kind"] == "package")
    assert package["label"] == "frontend"
    assert package["data"]["frameworks"] == ["react"]

    assert body["edges"] == [{
        "id": "depends_on:api:db",
        "source": "service:api",
        "target": "service:db",
        "type": "architecture_dependency",
        "data": {"certainty": "confirmed", "evidence": [{
            "path": "docker-compose.yml", "line": None, "basis": "config_file",
            "github_url": f"{BLOB}/docker-compose.yml",
        }]},
    }]


def test_architecture_partial_without_compose(seeded):
    add_file(seeded, "app.py", {"config_facts": [
        {"kind": "fastapi_app", "line": 4, "certainty": "confirmed"},
        {"kind": "fastapi_router", "line": 6, "certainty": "inferred"},
    ]})

    items = {item["type"]: item for item in seeded.client.get(f"/api/v1/analyses/{seeded.ids.run}/diagram-types").json()["items"]}
    assert items["architecture"]["availability"] == "partial"
    assert items["architecture"]["reason"]

    body = create(seeded, {"type": "architecture"}).json()
    assert body["availability"] == "partial"
    assert body["edges"] == []
    assert body["nodes"][0]["data"]["router_count"] == 1
    assert body["nodes"][0]["data"]["github_url"] == f"{BLOB}/app.py#L4"
