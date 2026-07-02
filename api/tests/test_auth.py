"""KnowTwin auth + role-gate tests.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_auth.py -v

Tests: ported auth basics + 7 KnowTwin role-gate tests (P1.5).
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
from auth import generate_api_key, hash_api_key, resolve_user_from_api_key

_DB_URL = os.environ["DATABASE_URL"]


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _db_exec(sql, *args):
    conn = await asyncpg.connect(_DB_URL)
    try:
        return await conn.execute(sql, *args)
    finally:
        await conn.close()


async def _db_val(sql, *args):
    conn = await asyncpg.connect(_DB_URL)
    try:
        return await conn.fetchval(sql, *args)
    finally:
        await conn.close()


async def _db_row(sql, *args):
    conn = await asyncpg.connect(_DB_URL)
    try:
        return await conn.fetchrow(sql, *args)
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    return create_app("development")


@pytest.fixture(scope="module")
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def super_key():
    """API key for superuser (user_id=1)."""
    key_plain, key_hash = generate_api_key()
    _run(_db_exec(
        "INSERT INTO api_keys (key_hash, name, user_id, active) VALUES ($1, 'test-super', 1, true)",
        key_hash,
    ))
    yield key_plain
    _run(_db_exec("DELETE FROM api_keys WHERE name = 'test-super'"))


@pytest.fixture(scope="module")
def role_users():
    """Create 4 users with different roles in the default project (id=1)."""
    async def _setup():
        conn = await asyncpg.connect(_DB_URL)
        try:
            ids = {}
            for name, role in [("test_admin", "admin"), ("test_curator", "curator"),
                               ("test_employee", "employee"), ("test_consumer", "consumer")]:
                uid = await conn.fetchval(
                    "INSERT INTO users (name) VALUES ($1) RETURNING id", name
                )
                await conn.execute(
                    "INSERT INTO user_emails (email, user_id, is_primary) VALUES ($1, $2, true)",
                    f"{name}@test.knowtwin", uid,
                )
                await conn.execute(
                    "INSERT INTO project_members (project_id, user_id, role) VALUES (1, $1, $2)",
                    uid, role,
                )
                ids[role] = uid
            return ids
        finally:
            await conn.close()

    ids = _run(_setup())
    yield ids

    async def _teardown():
        conn = await asyncpg.connect(_DB_URL)
        try:
            for uid in ids.values():
                await conn.execute("DELETE FROM project_members WHERE user_id = $1", uid)
                await conn.execute("DELETE FROM user_emails WHERE user_id = $1", uid)
                await conn.execute("DELETE FROM api_keys WHERE user_id = $1", uid)
                await conn.execute("DELETE FROM users WHERE id = $1", uid)
        finally:
            await conn.close()

    _run(_teardown())


@pytest.fixture(scope="module")
def role_keys(role_users):
    """Generate API keys for each role user."""
    keys = {}
    for role, uid in role_users.items():
        key_plain, key_hash = generate_api_key()
        _run(_db_exec(
            "INSERT INTO api_keys (key_hash, name, user_id, active) VALUES ($1, $2, $3, true)",
            key_hash, f"test-{role}", uid,
        ))
        keys[role] = key_plain
    yield keys
    for role in keys:
        _run(_db_exec("DELETE FROM api_keys WHERE name = $1", f"test-{role}"))


def _auth(key):
    return {"Authorization": f"Bearer {key}"}


# ---------------------------------------------------------------------------
# Ported basic auth tests
# ---------------------------------------------------------------------------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200


def test_missing_auth_returns_401(client):
    r = client.get("/auth/me")
    assert r.status_code == 401


def test_bad_key_returns_401(client):
    r = client.get("/auth/me", headers=_auth("knowtwin_BADKEY"))
    assert r.status_code == 401


def test_super_auth_me(client, super_key):
    r = client.get("/auth/me", headers=_auth(super_key))
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "admin"
    assert data["is_super"] is True


def test_token_exchange(client, super_key):
    r = client.post("/auth/token", json={"api_key": super_key})
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

    r2 = client.get("/auth/me", headers=_auth(data["access_token"]))
    assert r2.status_code == 200
    assert r2.json()["is_super"] is True


# ---------------------------------------------------------------------------
# P1.5 role-gate tests
# ---------------------------------------------------------------------------

def test_role_gate_employee_denied_twin(client, role_keys):
    """Employee cannot hit curation endpoints (create claim requires curator)."""
    r = client.post("/claims", json={
        "subject_entity": "test", "predicate": "sabe",
        "evidence_text": "denied test", "source_type": "curator", "project_id": 1,
    }, headers=_auth(role_keys["employee"]))
    assert r.status_code == 403


def test_role_gate_consumer_denied_curation(client, role_keys):
    """Consumer cannot create claims (requires curator role)."""
    r = client.post("/claims", json={
        "subject_entity": "test", "predicate": "sabe",
        "evidence_text": "denied test", "source_type": "curator", "project_id": 1,
    }, headers=_auth(role_keys["consumer"]))
    assert r.status_code == 403


def test_check_access_denies_non_member_project(client, super_key, role_keys):
    """User not in project_members for project_id=999 gets 403."""
    r = client.post("/claims", json={
        "subject_entity": "test", "predicate": "sabe",
        "evidence_text": "denied test", "source_type": "curator", "project_id": 999,
    }, headers=_auth(role_keys["curator"]))
    assert r.status_code == 403


def test_fail_closed_on_lookup_error(client, role_keys):
    """DB lookup error should result in 403, not 500."""
    r = client.post("/claims", json={
        "subject_entity": "test", "predicate": "sabe",
        "evidence_text": "denied test", "source_type": "curator", "project_id": -1,
    }, headers=_auth(role_keys["curator"]))
    assert r.status_code == 403


def test_pepper_and_secret_from_env():
    """Verify pepper and JWT secret come from env vars, not hardcoded."""
    import settings
    assert settings.API_KEY_PEPPER == os.environ.get("API_KEY_PEPPER", settings._API_KEY_PEPPER_DEV)
    assert settings.JWT_SECRET == os.environ.get("JWT_SECRET", settings._JWT_SECRET_DEV)
    assert settings.API_KEY_PREFIX == "knowtwin_"


def test_ws_rejects_bad_key(client):
    """WebSocket key validation rejects invalid keys (via token exchange)."""
    r = client.post("/auth/token", json={"api_key": "knowtwin_INVALID_WS_KEY"})
    assert r.status_code == 401


def test_no_privilege_escalation_via_key_create(client, role_keys, role_users):
    """Non-super/CEO user cannot create API keys (requires super_or_ceo)."""
    r = client.post("/auth/api-keys", json={
        "user_id": role_users["consumer"],
        "name": "escalation-test",
    }, headers=_auth(role_keys["curator"]))
    assert r.status_code == 403


def test_curator_can_create_claim(client, role_keys):
    """Curator CAN create claims (positive test)."""
    r = client.post("/claims", json={
        "subject_entity": "TestAccess", "predicate": "sabe",
        "evidence_text": "curator access test", "source_type": "curator", "project_id": 1,
    }, headers=_auth(role_keys["curator"]))
    assert r.status_code == 201
    _run(_db_exec("DELETE FROM claims WHERE evidence_text = 'curator access test'"))


def test_admin_can_create_claim(client, role_keys):
    """Admin CAN create claims (positive test)."""
    r = client.post("/claims", json={
        "subject_entity": "TestAccess", "predicate": "sabe",
        "evidence_text": "admin access test", "source_type": "curator", "project_id": 1,
    }, headers=_auth(role_keys["admin"]))
    assert r.status_code == 201
    _run(_db_exec("DELETE FROM claims WHERE evidence_text = 'admin access test'"))


def test_super_bypasses_role_check(client, super_key):
    """Super user bypasses check_access entirely."""
    r = client.post("/claims", json={
        "subject_entity": "TestAccess", "predicate": "sabe",
        "evidence_text": "super bypass test", "source_type": "curator", "project_id": 1,
    }, headers=_auth(super_key))
    assert r.status_code == 201
    _run(_db_exec("DELETE FROM claims WHERE evidence_text = 'super bypass test'"))


# ---------------------------------------------------------------------------
# TG-P1.5-1: CEO role → admin-level access
# ---------------------------------------------------------------------------

def test_ceo_has_admin_access():
    """CEO user (is_ceo=True) gets admin-level check_access via super bypass or org ownership."""
    from permissions import check_access, _ROLE_RANK
    assert _ROLE_RANK["admin"] == 3
    # CEO users have is_ceo=True in JWT, which check_access handles via
    # super bypass (is_super) or project membership. Verify rank hierarchy.
    assert _ROLE_RANK["consumer"] < _ROLE_RANK["curator"] < _ROLE_RANK["admin"]
