"""P1.12 coverage model tests — hand-computed fixtures, MUST match exactly.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_coverage.py -v
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
_PREFIX = "covtest_"
_ENTITY = f"{_PREFIX}TestEntity"
_PID = 1


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


@pytest.fixture(scope="module")
def client():
    app = create_app("development")
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def curator_headers():
    """Create a curator user + API key."""
    async def _setup():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval(
                "INSERT INTO users (name) VALUES ($1) RETURNING id", f"{_PREFIX}curator"
            )
            await conn.execute(
                "INSERT INTO user_emails (email, user_id, is_primary) VALUES ($1, $2, true)",
                f"{_PREFIX}curator@test.kt", uid,
            )
            await conn.execute(
                "INSERT INTO project_members (project_id, user_id, role) VALUES ($1, $2, 'curator')",
                _PID, uid,
            )
            kp, kh = generate_api_key()
            await conn.execute(
                "INSERT INTO api_keys (key_hash, name, user_id, active) VALUES ($1, $2, $3, true)",
                kh, f"{_PREFIX}curator_key", uid,
            )
            return kp
        finally:
            await conn.close()

    key = _run(_setup())
    yield {"Authorization": f"Bearer {key}"}

    async def _teardown():
        conn = await asyncpg.connect(_DB_URL)
        try:
            await conn.execute("DELETE FROM claims WHERE subject_entity = $1", _ENTITY)
            await conn.execute("DELETE FROM audit_log WHERE details::text LIKE $1", f"%{_PREFIX}%")
            await conn.execute("DELETE FROM api_keys WHERE name LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM project_members WHERE user_id IN (SELECT id FROM users WHERE name LIKE $1)", f"{_PREFIX}%")
            await conn.execute("DELETE FROM user_emails WHERE email LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM users WHERE name LIKE $1", f"{_PREFIX}%")
        finally:
            await conn.close()
    _run(_teardown())


@pytest.fixture(scope="module", autouse=True)
def seed_entity():
    """Seed test entity + expected_claims: expected_count=10, exp_crit=0.5 → denom=5.0."""
    _run(_db("DELETE FROM claims WHERE subject_entity = $1", _ENTITY))
    _run(_db("DELETE FROM entity_expected_claims WHERE entity_name = $1", _ENTITY))
    _run(_db("DELETE FROM nodes WHERE name = $1", _ENTITY))

    _run(_db(
        "INSERT INTO nodes (name, type, status) VALUES ($1, 'sistema_componente', 'active') "
        "ON CONFLICT (name) DO NOTHING",
        _ENTITY,
    ))
    _run(_db(
        "INSERT INTO entity_expected_claims "
        "(project_id, entity_name, entity_type, expected_count, expected_criticality) "
        "VALUES ($1, $2, 'sistema_componente', 10, 0.5) "
        "ON CONFLICT (project_id, entity_name) DO NOTHING",
        _PID, _ENTITY,
    ))

    yield

    _run(_db("DELETE FROM claims WHERE subject_entity = $1", _ENTITY))
    _run(_db("DELETE FROM entity_expected_claims WHERE entity_name = $1", _ENTITY))
    _run(_db("DELETE FROM nodes WHERE name = $1", _ENTITY))


def _insert_claim(crit, level, dispute="undisputed"):
    """Insert a claim directly at the given level (bypasses embed gate — no tei needed)."""
    uid = _run(_dbval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}curator"))
    _run(_db(
        "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
        "evidence_text, source_type, criticality, corroboration_level, dispute_state) "
        "VALUES ($1, $2, $3, 'test_pred', 'coverage test evidence', 'document', $4, $5, $6)",
        uid, _PID, _ENTITY, crit, level, dispute,
    ))


def test_coverage_zero_pre_claims(client, curator_headers):
    """No claims → coverage_state='unknown', pct=0."""
    resp = client.get(f"/twin/coverage?project_id={_PID}", headers=curator_headers)
    assert resp.status_code == 200
    entity = next((e for e in resp.json()["entities"] if e["entity_name"] == _ENTITY), None)
    assert entity is not None
    assert entity["coverage_state"] == "unknown"
    assert entity["coverage_pct"] == 0.0


def test_coverage_two_claims_hand_computed(client, curator_headers):
    """denom=10×0.5=5.0. 2 claims crit 0.9+0.6 → num=1.5 → pct=30.0."""
    _insert_claim(0.9, "single_source")
    _insert_claim(0.6, "single_source")

    resp = client.get(f"/twin/coverage?project_id={_PID}", headers=curator_headers)
    assert resp.status_code == 200
    entity = next(e for e in resp.json()["entities"] if e["entity_name"] == _ENTITY)
    assert entity["coverage_pct"] == 30.0
    assert entity["confirmed_count"] == 2
    assert entity["coverage_state"] == "partial"


def test_coverage_draft_excluded(client, curator_headers):
    """Add draft claim → pct unchanged (excluded from numerator)."""
    _insert_claim(0.8, "draft")

    resp = client.get(f"/twin/coverage?project_id={_PID}", headers=curator_headers)
    entity = next(e for e in resp.json()["entities"] if e["entity_name"] == _ENTITY)
    assert entity["coverage_pct"] == 30.0, "draft claim should not affect coverage"


def test_coverage_disputed_included(client, curator_headers):
    """Add disputed@single_source crit=0.5 → num=1.5+0.5=2.0 → pct=40.0."""
    _insert_claim(0.5, "single_source", dispute="disputed")

    resp = client.get(f"/twin/coverage?project_id={_PID}", headers=curator_headers)
    entity = next(e for e in resp.json()["entities"] if e["entity_name"] == _ENTITY)
    assert entity["coverage_pct"] == 40.0, "disputed@single_source should be included"
    assert entity["coverage_state"] == "disputed"


def test_coverage_entities_filter(client, curator_headers):
    """GET /graph/entities with coverage_state filter."""
    resp = client.get(f"/graph/entities?project_id={_PID}&coverage_state=unknown", headers=curator_headers)
    assert resp.status_code == 200
    entities = resp.json()["entities"]
    for e in entities:
        assert e["coverage_state"] == "unknown"
