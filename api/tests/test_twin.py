"""P1.16 Twin query tests — visibility, role gate, dispute handling.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_twin.py -v
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
_PREFIX = "twintest_"
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
def keys():
    """Create users: curator, employee, consumer + API keys."""
    async def _setup():
        conn = await asyncpg.connect(_DB_URL)
        try:
            result = {}
            for name, role in [("tw_curator", "curator"), ("tw_employee", "employee"), ("tw_consumer", "consumer")]:
                uid = await conn.fetchval(
                    "INSERT INTO users (name) VALUES ($1) RETURNING id", f"{_PREFIX}{name}"
                )
                await conn.execute(
                    "INSERT INTO user_emails (email, user_id, is_primary) VALUES ($1, $2, true)",
                    f"{_PREFIX}{name}@test.kt", uid,
                )
                await conn.execute(
                    "INSERT INTO project_members (project_id, user_id, role) VALUES ($1, $2, $3)",
                    _PID, uid, role,
                )
                kp, kh = generate_api_key()
                await conn.execute(
                    "INSERT INTO api_keys (key_hash, name, user_id, active) VALUES ($1, $2, $3, true)",
                    kh, f"{_PREFIX}{name}_key", uid,
                )
                result[role] = kp
            return result
        finally:
            await conn.close()

    k = _run(_setup())
    yield k

    async def _teardown():
        conn = await asyncpg.connect(_DB_URL)
        try:
            await conn.execute("DELETE FROM claims WHERE subject_entity LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM audit_log WHERE details::text LIKE $1", f"%{_PREFIX}%")
            await conn.execute("DELETE FROM api_keys WHERE name LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM project_members WHERE user_id IN (SELECT id FROM users WHERE name LIKE $1)", f"{_PREFIX}%")
            await conn.execute("DELETE FROM user_emails WHERE email LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM users WHERE name LIKE $1", f"{_PREFIX}%")
        finally:
            await conn.close()
    _run(_teardown())


def _auth(key):
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture(scope="module", autouse=True)
def seed_claims(keys):
    """Seed test claims: public+single_source, restricted+single_source, draft, disputed pair."""
    uid = _run(_dbval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}tw_curator"))

    _run(_db("DELETE FROM claims WHERE subject_entity LIKE $1", f"{_PREFIX}%"))

    _run(_db(
        "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
        "evidence_text, source_type, criticality, corroboration_level, sensitivity, dispute_state) "
        "VALUES ($1, $2, $3, 'manages', 'Public visible claim', 'document', 0.8, 'single_source', 'public', 'undisputed')",
        uid, _PID, f"{_PREFIX}EntityA",
    ))
    _run(_db(
        "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
        "evidence_text, source_type, criticality, corroboration_level, sensitivity, dispute_state) "
        "VALUES ($1, $2, $3, 'manages', 'Restricted claim not for consumer', 'document', 0.7, 'single_source', 'restricted', 'undisputed')",
        uid, _PID, f"{_PREFIX}EntityA",
    ))
    _run(_db(
        "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
        "evidence_text, source_type, criticality, corroboration_level, sensitivity, dispute_state) "
        "VALUES ($1, $2, $3, 'runs', 'Draft claim', 'document', 0.5, 'draft', 'public', 'undisputed')",
        uid, _PID, f"{_PREFIX}EntityB",
    ))
    _run(_db(
        "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
        "evidence_text, source_type, criticality, corroboration_level, sensitivity, dispute_state, doc_strength) "
        "VALUES ($1, $2, $3, 'sla_hours', 'SLA is 4 hours per contract', 'document', 0.9, 'single_source', 'public', 'disputed', 0.9)",
        uid, _PID, f"{_PREFIX}EntityC",
    ))
    _run(_db(
        "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
        "evidence_text, source_type, criticality, corroboration_level, sensitivity, dispute_state, doc_strength) "
        "VALUES ($1, $2, $3, 'sla_hours', 'SLA is 2 hours by verbal agreement', 'interview', 0.5, 'single_source', 'public', 'disputed', 0.3)",
        uid, _PID, f"{_PREFIX}EntityC",
    ))
    _run(_db(
        "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
        "evidence_text, source_type, criticality, corroboration_level, sensitivity, dispute_state) "
        "VALUES ($1, $2, $3, 'old_info', 'Resolved against - should be excluded', 'document', 0.3, 'single_source', 'public', 'resolved_against')",
        uid, _PID, f"{_PREFIX}EntityD",
    ))

    yield


def test_employee_denied_twin_query(client, keys):
    """Employee role → 403 on /twin/query."""
    resp = client.post("/twin/query", json={
        "question": "test question",
        "project_id": _PID,
    }, headers=_auth(keys["employee"]))
    assert resp.status_code == 403


def test_consumer_cannot_retrieve_restricted(client, keys):
    """Consumer sees public claims but NOT restricted ones."""
    resp = client.post("/twin/query", json={
        "question": f"{_PREFIX}EntityA",
        "project_id": _PID,
    }, headers=_auth(keys["consumer"]))
    assert resp.status_code == 200
    sources = resp.json()["sources"]
    for s in sources:
        assert s["sensitivity"] != "restricted", "consumer must not see restricted claims"


def test_rejected_and_draft_excluded(client, keys):
    """Draft and rejected claims never appear in sources."""
    resp = client.post("/twin/query", json={
        "question": f"{_PREFIX}EntityB draft",
        "project_id": _PID,
    }, headers=_auth(keys["curator"]))
    assert resp.status_code == 200
    sources = resp.json()["sources"]
    for s in sources:
        assert s["corroboration_level"] not in ("draft", "rejected"), \
            f"draft/rejected must not appear: {s['corroboration_level']}"


def test_disputed_returns_both_versions(client, keys):
    """Disputed claims appear as a dispute group with both versions."""
    resp = client.post("/twin/query", json={
        "question": f"{_PREFIX}EntityC sla",
        "project_id": _PID,
    }, headers=_auth(keys["curator"]))
    assert resp.status_code == 200
    data = resp.json()
    disputed_sources = [s for s in data["sources"] if s["dispute_state"] == "disputed"
                        and s["subject_entity"] == f"{_PREFIX}EntityC"]
    assert len(disputed_sources) >= 2, "both disputed versions should appear"


def test_resolved_against_excluded(client, keys):
    """resolved_against claims excluded from primary sources."""
    resp = client.post("/twin/query", json={
        "question": f"{_PREFIX}EntityD",
        "project_id": _PID,
    }, headers=_auth(keys["curator"]))
    assert resp.status_code == 200
    sources = resp.json()["sources"]
    for s in sources:
        assert s["dispute_state"] != "resolved_against", "resolved_against must be excluded"


def test_citation_mandatory_or_insufficient_info(client, keys):
    """Answer must have citations or state insufficient information."""
    resp = client.post("/twin/query", json={
        "question": "zxqwj9k7m3p2 qqq999zzz",
        "project_id": _PID,
    }, headers=_auth(keys["curator"]))
    assert resp.status_code == 200
    data = resp.json()
    answer = data["answer"]
    if data["sources"]:
        assert "[" in answer and "]" in answer, "answer with sources must cite them"
    else:
        assert "insufficient information" in answer.lower(), \
            f"answer without sources must state insufficient info, got: {answer[:100]}"


def test_twin_is_readonly(client, keys):
    """/twin/query is POST but read-only (no side effects). GET/PUT/DELETE → 405."""
    resp = client.get("/twin/query", headers=_auth(keys["curator"]))
    assert resp.status_code in (405, 422)
    resp = client.put("/twin/query", json={
        "question": "test", "project_id": _PID,
    }, headers=_auth(keys["curator"]))
    assert resp.status_code == 405
    resp = client.delete("/twin/query", headers=_auth(keys["curator"]))
    assert resp.status_code == 405
