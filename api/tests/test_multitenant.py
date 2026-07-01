"""Multitenant tests — ported from EcoDB, adapted for KnowTwin claims.

Tests project isolation: users in project A can't see claims in project B.
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


@pytest.fixture(scope="module")
def client():
    app = create_app("development")
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def mt_setup():
    """Create two projects with separate curators + claims."""
    async def _setup():
        conn = await asyncpg.connect(_DB_URL)
        try:
            p2 = await conn.fetchval(
                "INSERT INTO projects (workspace_id, name) VALUES (1, 'mt_project_b') RETURNING id"
            )

            u1 = await conn.fetchval("INSERT INTO users (name) VALUES ('mt_curator_a') RETURNING id")
            u2 = await conn.fetchval("INSERT INTO users (name) VALUES ('mt_curator_b') RETURNING id")

            await conn.execute("INSERT INTO user_emails (email, user_id, is_primary) VALUES ($1, $2, true)", "mt_a@test.kt", u1)
            await conn.execute("INSERT INTO user_emails (email, user_id, is_primary) VALUES ($1, $2, true)", "mt_b@test.kt", u2)

            await conn.execute("INSERT INTO project_members (project_id, user_id, role) VALUES (1, $1, 'curator')", u1)
            await conn.execute("INSERT INTO project_members (project_id, user_id, role) VALUES ($1, $2, 'curator')", p2, u2)

            k1p, k1h = generate_api_key()
            k2p, k2h = generate_api_key()
            await conn.execute("INSERT INTO api_keys (key_hash, name, user_id, active) VALUES ($1, 'mt-a', $2, true)", k1h, u1)
            await conn.execute("INSERT INTO api_keys (key_hash, name, user_id, active) VALUES ($1, 'mt-b', $2, true)", k2h, u2)

            await conn.execute(
                """INSERT INTO claims (project_id, subject_entity, predicate, evidence_text,
                   source_type, corroboration_level, sensitivity)
                   VALUES (1, 'A_Entity', 'sabe', 'MT_claim_a', 'curator', 'single_source', 'public')""")
            await conn.execute(
                """INSERT INTO claims (project_id, subject_entity, predicate, evidence_text,
                   source_type, corroboration_level, sensitivity)
                   VALUES ($1, 'B_Entity', 'sabe', 'MT_claim_b', 'curator', 'single_source', 'public')""",
                p2)

            return {"p2": p2, "u1": u1, "u2": u2, "k1": k1p, "k2": k2p}
        finally:
            await conn.close()

    data = _run(_setup())
    yield data

    async def _teardown():
        conn = await asyncpg.connect(_DB_URL)
        try:
            await conn.execute("DELETE FROM claims WHERE evidence_text LIKE 'MT_%'")
            await conn.execute("DELETE FROM audit_log WHERE user_id IN ($1, $2)", data["u1"], data["u2"])
            await conn.execute("DELETE FROM api_keys WHERE user_id IN ($1, $2)", data["u1"], data["u2"])
            await conn.execute("DELETE FROM project_members WHERE user_id IN ($1, $2)", data["u1"], data["u2"])
            await conn.execute("DELETE FROM user_emails WHERE user_id IN ($1, $2)", data["u1"], data["u2"])
            await conn.execute("DELETE FROM projects WHERE id = $1", data["p2"])
            await conn.execute("DELETE FROM users WHERE id IN ($1, $2)", data["u1"], data["u2"])
        finally:
            await conn.close()

    _run(_teardown())


def _h(key):
    return {"Authorization": f"Bearer {key}"}


def test_curator_a_sees_project_a_claims(client, mt_setup):
    r = client.get("/claims", params={"project_id": 1}, headers=_h(mt_setup["k1"]))
    assert r.status_code == 200
    texts = {i["evidence_text"] for i in r.json()["items"]}
    assert "MT_claim_a" in texts


def test_curator_a_cannot_see_project_b(client, mt_setup):
    r = client.get("/claims", params={"project_id": mt_setup["p2"]}, headers=_h(mt_setup["k1"]))
    assert r.status_code == 403, "curator_a is not a member of project_b"


def test_curator_b_sees_project_b_claims(client, mt_setup):
    r = client.get("/claims", params={"project_id": mt_setup["p2"]}, headers=_h(mt_setup["k2"]))
    assert r.status_code == 200
    texts = {i["evidence_text"] for i in r.json()["items"]}
    assert "MT_claim_b" in texts


def test_curator_b_cannot_see_project_a(client, mt_setup):
    r = client.get("/claims", params={"project_id": 1}, headers=_h(mt_setup["k2"]))
    assert r.status_code == 403


def test_curator_a_cannot_create_in_project_b(client, mt_setup):
    r = client.post("/claims", json={
        "subject_entity": "Cross", "predicate": "sabe",
        "evidence_text": "MT_cross_project", "source_type": "curator",
        "project_id": mt_setup["p2"],
    }, headers=_h(mt_setup["k1"]))
    assert r.status_code == 403


def test_no_memories_table():
    """Sweep: memories table must not exist."""
    exists = _run(_dbval(
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'memories')"
    ))
    assert not exists, "memories table must not exist in KnowTwin"
