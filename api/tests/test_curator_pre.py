"""P1.9 Curator pre-interview tests — DB state assertions, monkeypatched LLM.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_curator_pre.py -v
"""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql://knowtwin:knowtwin_test_pass@knowtwin-db:5432/knowtwin")
os.environ.setdefault("ENVIRONMENT", "development")

import asyncpg
from fastapi.testclient import TestClient

from main import create_app
from auth import generate_api_key
from curator import trust_tier_from_hint, _identify_gaps, _detect_contradictions

_DB_URL = os.environ["DATABASE_URL"]
_PREFIX = "curtest_"
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


async def _dbrows(sql, *args):
    conn = await asyncpg.connect(_DB_URL)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


@pytest.fixture(scope="module")
def client():
    app = create_app("development")
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def curator_key():
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
    yield key

    async def _teardown():
        conn = await asyncpg.connect(_DB_URL)
        try:
            await conn.execute("DELETE FROM verified_documents WHERE project_id = $1 AND domain_area LIKE $2", _PID, f"%{_PREFIX}%")
            await conn.execute("DELETE FROM claims WHERE subject_entity LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM audit_log WHERE details::text LIKE $1", f"%{_PREFIX}%")
            await conn.execute("DELETE FROM api_keys WHERE name LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM project_members WHERE user_id IN (SELECT id FROM users WHERE name LIKE $1)", f"{_PREFIX}%")
            await conn.execute("DELETE FROM user_emails WHERE email LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM users WHERE name LIKE $1", f"{_PREFIX}%")
        finally:
            await conn.close()
    _run(_teardown())


# CP4: trust_tier from trust_hint
def test_trust_tier_mapping():
    assert trust_tier_from_hint("formal_contract") == 2
    assert trust_tier_from_hint("adr") == 2
    assert trust_tier_from_hint("signed_plan") == 2
    assert trust_tier_from_hint("wiki") == 1
    assert trust_tier_from_hint("presentation") == 1
    assert trust_tier_from_hint("email") == 1
    assert trust_tier_from_hint("orgchart") == 0
    assert trust_tier_from_hint("other") == 0
    assert trust_tier_from_hint(None) == 0


# CP2: contradiction detection
def test_contradiction_detection():
    uid = _run(_dbval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}curator"))

    _run(_db("DELETE FROM claims WHERE subject_entity LIKE $1", f"{_PREFIX}%"))
    _run(_db(
        "INSERT INTO claims (user_id, project_id, subject_entity, predicate, object_value, "
        "evidence_text, source_type, corroboration_level, sensitivity) "
        "VALUES ($1, $2, $3, 'sla_hours', '4 hours', 'Contract says 4h', 'document', 'single_source', 'public')",
        uid, _PID, f"{_PREFIX}CloudBase",
    ))
    _run(_db(
        "INSERT INTO claims (user_id, project_id, subject_entity, predicate, object_value, "
        "evidence_text, source_type, corroboration_level, sensitivity) "
        "VALUES ($1, $2, $3, 'sla_hours', '2 hours', 'Verbal agreement 2h', 'interview', 'single_source', 'public')",
        uid, _PID, f"{_PREFIX}CloudBase",
    ))

    async def _detect():
        conn = await asyncpg.connect(_DB_URL)
        try:
            return await _detect_contradictions(conn, _PID)
        finally:
            await conn.close()

    contradictions = _run(_detect())
    assert len(contradictions) >= 1, "should detect doc-vs-doc contradiction"

    rows = _run(_dbrows(
        "SELECT dispute_state FROM claims WHERE subject_entity = $1 AND predicate = 'sla_hours'",
        f"{_PREFIX}CloudBase",
    ))
    assert all(r["dispute_state"] == "disputed" for r in rows), "both claims should be disputed"


# CP3: gap identification
def test_gap_identification():
    _run(_db(
        "INSERT INTO entity_expected_claims (project_id, entity_name, entity_type, expected_count) "
        "VALUES ($1, $2, 'cliente_cuenta', 12) ON CONFLICT DO NOTHING",
        _PID, f"{_PREFIX}GapClient",
    ))

    async def _gaps():
        conn = await asyncpg.connect(_DB_URL)
        try:
            return await _identify_gaps(conn, _PID)
        finally:
            await conn.close()

    gaps = _run(_gaps())
    gap_entity = next((g for g in gaps if g["entity_name"] == f"{_PREFIX}GapClient"), None)
    assert gap_entity is not None, "gap entity should be found"
    assert "decide_en" in gap_entity["missing_predicates"], "[GAP] decide_en should be missing"

    _run(_db("DELETE FROM entity_expected_claims WHERE entity_name = $1", f"{_PREFIX}GapClient"))


# CP5: entity_expected_claims seeded
def test_expected_claims_seeded(client, curator_key):
    """Curator seeds entity_expected_claims for entities in claims."""
    uid = _run(_dbval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}curator"))

    _run(_db(
        "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
        "evidence_text, source_type, corroboration_level, sensitivity) "
        "VALUES ($1, $2, $3, 'manages', 'Test claim', 'document', 'single_source', 'public')",
        uid, _PID, f"{_PREFIX}NewEntity",
    ))
    _run(_db(
        "INSERT INTO nodes (name, type, status) VALUES ($1, 'persona_interna', 'active') ON CONFLICT DO NOTHING",
        f"{_PREFIX}NewEntity",
    ))

    from curator import _seed_expected_claims
    async def _seed():
        conn = await asyncpg.connect(_DB_URL)
        try:
            return await _seed_expected_claims(conn, _PID)
        finally:
            await conn.close()

    count = _run(_seed())
    assert count >= 1

    row = _run(_dbval(
        "SELECT expected_count FROM entity_expected_claims WHERE project_id = $1 AND entity_name = $2",
        _PID, f"{_PREFIX}NewEntity",
    ))
    assert row is not None, "expected_claims should be seeded"

    _run(_db("DELETE FROM entity_expected_claims WHERE entity_name = $1", f"{_PREFIX}NewEntity"))
    _run(_db("DELETE FROM nodes WHERE name = $1", f"{_PREFIX}NewEntity"))


# CP7: idempotent (advisory lock)
def test_curator_idempotent(client, curator_key):
    """Second concurrent run returns already_running when lock held."""
    import hashlib

    async def _test():
        pool = await asyncpg.create_pool(_DB_URL, min_size=2, max_size=3)
        lock_key = int(hashlib.sha256(f"curator_pre:{_PID}".encode()).hexdigest()[:15], 16)
        lock_conn = await asyncpg.connect(_DB_URL)
        try:
            await lock_conn.execute("SELECT pg_advisory_lock($1)", lock_key)
            from curator import run_curator_pre
            result = await run_curator_pre(pool, _PID, 1)
            assert result.get("error") == "already_running"
        finally:
            await lock_conn.execute("SELECT pg_advisory_unlock($1)", lock_key)
            await lock_conn.close()
            await pool.close()

    _run(_test())
