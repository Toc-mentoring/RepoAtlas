import json
from dataclasses import asdict

from worker.parsers.config_facts import parse_config, parse_python_facts
from worker.parsers.sql_ddl import parse_sql


def test_postgres_ddl_extracts_primary_and_composite_foreign_keys():
    sql = b'''
CREATE TABLE accounts (tenant_id BIGINT, id BIGINT, PRIMARY KEY (tenant_id, id));
CREATE TABLE sales.orders (
  id BIGINT PRIMARY KEY,
  tenant_id BIGINT NOT NULL,
  account_id BIGINT,
  note TEXT DEFAULT 'secret value',
  CONSTRAINT fk_account FOREIGN KEY (tenant_id, account_id) REFERENCES accounts(tenant_id, id)
);
'''
    tables, warnings = parse_sql("schema.sql", sql)
    assert not warnings
    accounts, orders = tables
    assert (accounts.schema_name, accounts.name) == ("public", "accounts")
    assert [(c.name, c.is_primary, c.is_nullable) for c in accounts.columns] == [
        ("tenant_id", True, False), ("id", True, False),
    ]
    assert (orders.schema_name, orders.name) == ("sales", "orders")
    assert [(f.source_column, f.target_ref, f.ordinal_position, f.constraint_name) for f in orders.foreign_keys] == [
        ("tenant_id", "public.accounts(tenant_id)", 1, "fk_account"),
        ("account_id", "public.accounts(id)", 2, "fk_account"),
    ]
    assert "secret value" not in json.dumps([asdict(t) for t in tables])


def test_inline_and_unresolved_foreign_keys_and_unsupported_ddl():
    sql = b'CREATE TABLE child (parent_id INT REFERENCES parents(id), other INT REFERENCES unknown); ALTER TABLE child ADD COLUMN extra TEXT;'
    tables, warnings = parse_sql("migration.sql", sql)
    assert len(tables) == 1
    assert [(f.source_column, f.target_column) for f in tables[0].foreign_keys] == [("parent_id", "id"), ("other", None)]
    assert any("ALTER TABLE" in warning for warning in warnings)
    assert parse_sql("broken.sql", b"CREATE TABLE broken (")[1]


def test_config_facts_do_not_keep_secret_values():
    compose = b'''services:
  api:
    environment:
      DATABASE_URL: postgresql://user:supersecret@db/app
    depends_on: [db]
  db:
    image: postgres:16
'''
    facts, warnings = parse_config("compose.yml", compose)
    assert facts == [
        {"kind": "service", "name": "api", "certainty": "confirmed"},
        {"kind": "depends_on", "source": "api", "target": "db", "certainty": "confirmed"},
        {"kind": "service", "name": "db", "certainty": "confirmed"},
    ]
    assert not warnings and "supersecret" not in json.dumps(facts)
    facts, warnings = parse_config("package.json", b'{"dependencies":{"react":"secret-version"},"scripts":{"build":"secret-command"}}')
    assert {fact["name"] for fact in facts} == {"react", "build"}
    assert "secret" not in json.dumps(facts)
    assert not warnings


def test_unsafe_yaml_is_not_executed_and_fastapi_facts_have_lines():
    facts, warnings = parse_config("compose.yml", b'services: !!python/object/apply:os.system ["echo unsafe"]')
    assert facts == [] and warnings
    facts = parse_python_facts("main.py", b'from fastapi import FastAPI\napp = FastAPI()\napp.include_router(router)\n')
    assert facts == [
        {"kind": "fastapi_app", "line": 2, "certainty": "confirmed"},
        {"kind": "fastapi_router", "line": 3, "certainty": "inferred"},
    ]


def test_unsupported_sql_does_not_leak_source_to_logs(caplog):
    tables, warnings = parse_sql("schema.sql", b"VACUUM secretvalue;")
    assert tables == [] and warnings == ["Unsupported SQL statement: schema.sql"]
    assert "secretvalue" not in caplog.text
