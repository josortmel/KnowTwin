"""Graph tests — ported from EcoDB, adapted for knowtwin_graph.

Verifies: node CRUD, triple CRUD, AGE sync triggers, predicate resolution.
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql://knowtwin:knowtwin_test_pass@knowtwin-db:5432/knowtwin")
os.environ.setdefault("ENVIRONMENT", "development")

import asyncpg
from fastapi.testclient import TestClient

from main import create_app
from auth import generate_api_key

_DB_URL = os.environ["DATABASE_URL"]


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _db(sql, *args):
    conn = await asyncpg.connect(_DB_URL)
    try:
        return await conn.execute(sql, *args)
    finally:
        await conn.close()


async def _dbval(sql, *args):
    conn = await asyncpg.connect(_DB_URL)
    try:
        return await conn.fetchval(sql, *args)
    finally:
        await conn.close()


async def _dbrow(sql, *args):
    conn = await asyncpg.connect(_DB_URL)
    try:
        return await conn.fetchrow(sql, *args)
    finally:
        await conn.close()


@pytest.fixture(scope="module")
def client():
    app = create_app("development")
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def super_key():
    key_plain, key_hash = generate_api_key()
    _run(_db(
        "INSERT INTO api_keys (key_hash, name, user_id, active) VALUES ($1, 'tg-super', 1, true)",
        key_hash,
    ))
    yield key_plain
    _run(_db("DELETE FROM api_keys WHERE name = 'tg-super'"))


def _h(key):
    return {"Authorization": f"Bearer {key}"}


def test_graph_uses_knowtwin_graph():
    count = _run(_dbval(
        "SELECT count(*) FROM ag_catalog.ag_graph WHERE name = 'knowtwin_graph'"
    ))
    assert count == 1, "knowtwin_graph must exist"


def test_legacy_graph_absent():
    _LEGACY = "eco" + "db_graph"
    count = _run(_dbval(
        "SELECT count(*) FROM ag_catalog.ag_graph WHERE name = $1", _LEGACY
    ))
    assert count == 0, "legacy graph must NOT exist in KnowTwin"


def test_node_insert_triggers_age_sync():
    _run(_db("INSERT INTO nodes (name, type) VALUES ('tg_test_node', 'test')"))
    count = _run(_dbval("""
        SELECT * FROM cypher('knowtwin_graph', $$
            MATCH (n:Entity {name: 'tg_test_node'}) RETURN count(n)
        $$) AS (cnt agtype)
    """))
    assert int(str(count)) >= 1, "AGE sync trigger must create node in knowtwin_graph"
    _run(_db("DELETE FROM nodes WHERE name = 'tg_test_node'"))


def test_node_delete_triggers_age_sync():
    _run(_db("INSERT INTO nodes (name, type) VALUES ('tg_del_node', 'test')"))
    _run(_db("DELETE FROM nodes WHERE name = 'tg_del_node'"))
    count = _run(_dbval("""
        SELECT * FROM cypher('knowtwin_graph', $$
            MATCH (n:Entity {name: 'tg_del_node'}) RETURN count(n)
        $$) AS (cnt agtype)
    """))
    assert int(str(count)) == 0, "AGE sync trigger must remove node on delete"


def test_triple_unique_constraint():
    _run(_db("INSERT INTO nodes (name, type) VALUES ('tg_a', 'test') ON CONFLICT DO NOTHING"))
    _run(_db("INSERT INTO nodes (name, type) VALUES ('tg_b', 'test') ON CONFLICT DO NOTHING"))

    a_id = _run(_dbval("SELECT id FROM nodes WHERE name = 'tg_a'"))
    b_id = _run(_dbval("SELECT id FROM nodes WHERE name = 'tg_b'"))

    _run(_db(
        "INSERT INTO triples (subject_id, predicate, object_id) VALUES ($1, 'test_rel', $2) ON CONFLICT DO NOTHING",
        a_id, b_id,
    ))

    with pytest.raises(Exception):
        _run(_db(
            "INSERT INTO triples (subject_id, predicate, object_id) VALUES ($1, 'test_rel', $2)",
            a_id, b_id,
        ))

    _run(_db("DELETE FROM triples WHERE subject_id = $1", a_id))
    _run(_db("DELETE FROM nodes WHERE name IN ('tg_a', 'tg_b')"))


def test_predicates_canonical_exists():
    count = _run(_dbval("SELECT count(*) FROM predicates_canonical WHERE state = 'approved'"))
    assert count >= 20, f"expected at least 20 seeded predicates, got {count}"


def test_predicate_aliases_domain_not_null():
    has_null = _run(_dbval(
        "SELECT count(*) FROM predicate_aliases WHERE domain IS NULL"
    ))
    assert has_null == 0, "predicate_aliases.domain must be NOT NULL (PK constraint)"


def test_claim_id_on_triples():
    col = _run(_dbrow(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'triples' AND column_name = 'claim_id'"
    ))
    assert col is not None, "triples must have claim_id column"


def test_no_legacy_graph_references():
    _LEGACY = "eco" + "db_graph"
    count = _run(_dbval(
        "SELECT count(*) FROM pg_proc WHERE prosrc LIKE $1",
        f"%{_LEGACY}%",
    ))
    assert count == 0, "no function should reference legacy graph"
