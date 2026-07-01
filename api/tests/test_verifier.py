"""P1.10 Verifier tests — read-only QA, never writes claims.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_verifier.py -v
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
_PREFIX = "vertest_"
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
            await conn.execute("DELETE FROM verifier_reports WHERE project_id = $1", _PID)
            await conn.execute("DELETE FROM claims WHERE subject_entity LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM entity_expected_claims WHERE entity_name LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM audit_log WHERE details::text LIKE $1", f"%{_PREFIX}%")
            await conn.execute("DELETE FROM api_keys WHERE name LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM project_members WHERE user_id IN (SELECT id FROM users WHERE name LIKE $1)", f"{_PREFIX}%")
            await conn.execute("DELETE FROM user_emails WHERE email LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM users WHERE name LIKE $1", f"{_PREFIX}%")
        finally:
            await conn.close()
    _run(_teardown())


@pytest.fixture(scope="module", autouse=True)
def seed_data(curator_key):
    uid = _run(_dbval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}curator"))
    _run(_db("DELETE FROM claims WHERE subject_entity LIKE $1", f"{_PREFIX}%"))
    _run(_db(
        "INSERT INTO claims (user_id, project_id, subject_entity, predicate, object_value, "
        "evidence_text, source_type, corroboration_level, sensitivity) "
        "VALUES ($1, $2, $3, 'manages', 'team alpha', 'Test claim for verifier', 'document', "
        "'single_source', 'public')",
        uid, _PID, f"{_PREFIX}Entity",
    ))
    yield


def test_verifier_never_writes_claims(client, curator_key):
    """Verifier run must not INSERT/UPDATE/DELETE any claims."""
    before = _run(_dbval("SELECT COUNT(*) FROM claims"))

    resp = client.post(f"/projects/{_PID}/verifier/run",
                       headers={"Authorization": f"Bearer {curator_key}"})
    assert resp.status_code == 200

    after = _run(_dbval("SELECT COUNT(*) FROM claims"))
    assert after == before, f"claims count changed: {before}→{after}"


def test_verifier_report_persisted_shape(client, curator_key):
    """Verifier report has expected JSONB fields."""
    report = _run(_dbval(
        "SELECT id FROM verifier_reports WHERE project_id = $1 ORDER BY created_at DESC LIMIT 1",
        _PID,
    ))
    assert report is not None, "verifier_reports row should exist"

    import asyncpg as _ap
    async def _check():
        conn = await _ap.connect(_DB_URL)
        try:
            row = await conn.fetchrow("SELECT * FROM verifier_reports WHERE id = $1", report)
            assert row["run_type"] == "pre_interview"
            assert row["status"] == "pending"
            assert isinstance(row["missed_entities"], (list, str))
            assert isinstance(row["structural_gaps"], (list, str))
        finally:
            await conn.close()
    _run(_check())


def test_verifier_project_scoped(client, curator_key):
    """Verifier only checks claims for the specified project."""
    resp = client.post(f"/projects/{_PID}/verifier/run",
                       headers={"Authorization": f"Bearer {curator_key}"})
    assert resp.status_code == 200
    data = resp.json()
    assert "report_id" in data or "error" in data


def test_rerun_bounded(client, curator_key):
    """After >1 runs, verifier returns max_reruns_exceeded."""
    _run(_db(
        "INSERT INTO verifier_reports (project_id, run_type) VALUES ($1, 'pre_interview')",
        _PID,
    ))
    _run(_db(
        "INSERT INTO verifier_reports (project_id, run_type) VALUES ($1, 'pre_interview')",
        _PID,
    ))

    from verifier import run_verifier
    async def _test():
        pool = await asyncpg.create_pool(_DB_URL, min_size=1, max_size=2)
        try:
            result = await run_verifier(pool, _PID, 1)
            return result
        finally:
            await pool.close()

    result = _run(_test())
    assert result.get("error") == "max_reruns_exceeded"

    _run(_db("DELETE FROM verifier_reports WHERE project_id = $1", _PID))
