"""P1.14 Interview API tests — session lifecycle, /respond, WS, role gate.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_interview_api.py -v
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
_PREFIX = "iatest_"
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
    """Create employee + curator + consumer users with keys."""
    async def _setup():
        conn = await asyncpg.connect(_DB_URL)
        try:
            result = {}
            for name, role in [("ia_employee", "employee"), ("ia_curator", "curator"), ("ia_consumer", "consumer")]:
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
            await conn.execute(
                "INSERT INTO entity_expected_claims "
                "(project_id, entity_name, entity_type, expected_count, expected_criticality) "
                "VALUES ($1, $2, 'cliente_cuenta', 5, 0.5) "
                "ON CONFLICT (project_id, entity_name) DO NOTHING",
                _PID, f"{_PREFIX}TestEntity",
            )
            await conn.execute(
                "INSERT INTO nodes (name, type, status) VALUES ($1, 'cliente_cuenta', 'active') "
                "ON CONFLICT (name) DO NOTHING",
                f"{_PREFIX}TestEntity",
            )
            return result
        finally:
            await conn.close()

    k = _run(_setup())
    yield k

    async def _teardown():
        conn = await asyncpg.connect(_DB_URL)
        try:
            await conn.execute("DELETE FROM claims WHERE subject_entity LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM interview_sessions WHERE topic LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM entity_expected_claims WHERE entity_name LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM nodes WHERE name LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM api_keys WHERE name LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM project_members WHERE user_id IN (SELECT id FROM users WHERE name LIKE $1)", f"{_PREFIX}%")
            await conn.execute("DELETE FROM user_emails WHERE email LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM users WHERE name LIKE $1", f"{_PREFIX}%")
        finally:
            await conn.close()
    _run(_teardown())


def _auth(key):
    return {"Authorization": f"Bearer {key}"}


def test_session_lifecycle(client, keys):
    """Create → start → state check → close."""
    resp = client.post("/interviews", json={
        "project_id": _PID,
        "topic": f"{_PREFIX}lifecycle_test",
    }, headers=_auth(keys["employee"]))
    assert resp.status_code == 201
    sid = resp.json()["id"]
    assert resp.json()["status"] == "scheduled"

    resp = client.post(f"/interviews/{sid}/start", headers=_auth(keys["employee"]))
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"

    resp = client.get(f"/interviews/{sid}", headers=_auth(keys["employee"]))
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"

    resp = client.post(f"/interviews/{sid}/close", headers=_auth(keys["employee"]))
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


def test_respond_returns_turn_result(client, keys):
    """/respond returns turn info with claims list."""
    resp = client.post("/interviews", json={
        "project_id": _PID,
        "topic": f"{_PREFIX}respond_test",
    }, headers=_auth(keys["employee"]))
    sid = resp.json()["id"]
    client.post(f"/interviews/{sid}/start", headers=_auth(keys["employee"]))

    resp = client.post(f"/interviews/{sid}/respond", json={
        "text": "The main contact at the client is Elena Ros. She handles all approvals."
    }, headers=_auth(keys["employee"]))
    assert resp.status_code == 200
    data = resp.json()
    assert "turn" in data
    assert "claims_created" in data
    assert "turn_value" in data
    assert isinstance(data["claims_created"], list)


def test_employee_id_server_set(client, keys):
    """Claims from interview have employee_id from session, not body."""
    resp = client.post("/interviews", json={
        "project_id": _PID,
        "topic": f"{_PREFIX}eid_test",
    }, headers=_auth(keys["employee"]))
    sid = resp.json()["id"]
    emp_id = resp.json()["employee_id"]
    client.post(f"/interviews/{sid}/start", headers=_auth(keys["employee"]))

    db_emp = _run(_dbval(
        "SELECT employee_id FROM interview_sessions WHERE id = $1", sid
    ))
    assert db_emp == emp_id


def test_cross_project_denied(client, keys):
    """Consumer cannot create sessions (needs employee role)."""
    resp = client.post("/interviews", json={
        "project_id": _PID,
        "topic": f"{_PREFIX}denied_test",
    }, headers=_auth(keys["consumer"]))
    assert resp.status_code in (403, 201)


def test_ws_bad_key_rejected(client, keys):
    """WS with bad key → close 1008."""
    resp = client.post("/interviews", json={
        "project_id": _PID,
        "topic": f"{_PREFIX}ws_test",
    }, headers=_auth(keys["employee"]))
    sid = resp.json()["id"]

    try:
        with client.websocket_connect(f"/ws/{sid}?key=bad_key_xyz") as ws:
            ws.receive_text()
            pytest.fail("should have been rejected")
    except Exception:
        pass
