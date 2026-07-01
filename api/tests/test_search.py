"""Search/visibility tests — adapted for KnowTwin claims.

Tests claim LIST endpoint (GET /claims) with IN-list filter, dispute_state,
and sensitivity visibility per role. Full GAMR search adaptation is P1.16.
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


@pytest.fixture(scope="module")
def client():
    app = create_app("development")
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def users_and_keys():
    async def _setup():
        conn = await asyncpg.connect(_DB_URL)
        try:
            result = {}
            for name, role in [("ts_curator", "curator"), ("ts_consumer", "consumer"), ("ts_employee", "employee")]:
                uid = await conn.fetchval("INSERT INTO users (name) VALUES ($1) RETURNING id", name)
                await conn.execute(
                    "INSERT INTO user_emails (email, user_id, is_primary) VALUES ($1, $2, true)",
                    f"{name}@test.kt", uid)
                await conn.execute(
                    "INSERT INTO project_members (project_id, user_id, role) VALUES (1, $1, $2)",
                    uid, role)
                kp, kh = generate_api_key()
                await conn.execute(
                    "INSERT INTO api_keys (key_hash, name, user_id, active) VALUES ($1, $2, $3, true)",
                    kh, f"ts-{name}", uid)
                result[role] = {"key": kp, "uid": uid}
            return result
        finally:
            await conn.close()

    data = _run(_setup())
    yield data

    async def _teardown():
        conn = await asyncpg.connect(_DB_URL)
        try:
            await conn.execute("DELETE FROM claims WHERE evidence_text LIKE 'TS_%'")
            for info in data.values():
                await conn.execute("DELETE FROM audit_log WHERE user_id = $1", info["uid"])
                await conn.execute("DELETE FROM api_keys WHERE user_id = $1", info["uid"])
                await conn.execute("DELETE FROM project_members WHERE user_id = $1", info["uid"])
                await conn.execute("DELETE FROM user_emails WHERE user_id = $1", info["uid"])
                await conn.execute("DELETE FROM users WHERE id = $1", info["uid"])
        finally:
            await conn.close()

    _run(_teardown())


def _h(key):
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture(scope="module", autouse=True)
def seed_claims(users_and_keys):
    eid = users_and_keys["employee"]["uid"]
    _run(_db(
        """INSERT INTO claims (project_id, subject_entity, predicate, evidence_text,
           source_type, corroboration_level, sensitivity, employee_id)
           VALUES
           (1, 'Entity1', 'sabe', 'TS_public_single', 'curator', 'single_source', 'public', NULL),
           (1, 'Entity2', 'sabe', 'TS_restricted_validated', 'curator', 'validated', 'restricted', NULL),
           (1, 'Entity3', 'sabe', 'TS_draft_claim', 'curator', 'draft', 'public', NULL),
           (1, 'Entity4', 'sabe', 'TS_rejected_claim', 'curator', 'rejected', 'public', NULL),
           (1, 'Entity5', 'sabe', 'TS_disputed_claim', 'curator', 'single_source', 'public', NULL),
           (1, 'EmpEntity', 'sabe', 'TS_employee_claim', 'interview', 'single_source', 'restricted', $1)""",
        eid,
    ))
    _run(_db("UPDATE claims SET dispute_state = 'disputed' WHERE evidence_text = 'TS_disputed_claim'"))
    yield
    _run(_db("DELETE FROM claims WHERE evidence_text LIKE 'TS_%'"))


def test_consumer_sees_only_inlist_public(client, users_and_keys):
    r = client.get("/claims", params={"project_id": 1}, headers=_h(users_and_keys["consumer"]["key"]))
    assert r.status_code == 200
    items = r.json()["items"]
    for item in items:
        if item["evidence_text"].startswith("TS_"):
            assert item["corroboration_level"] in (
                "single_source", "corroborated", "corroborated_by_employee", "validated"
            ), f"consumer sees non-IN-list level: {item['corroboration_level']}"
            assert item["sensitivity"] in ("public", "team"), \
                f"consumer sees restricted: {item['evidence_text']}"


def test_consumer_never_sees_draft(client, users_and_keys):
    r = client.get("/claims", params={"project_id": 1}, headers=_h(users_and_keys["consumer"]["key"]))
    for item in r.json()["items"]:
        assert item["corroboration_level"] != "draft"


def test_consumer_never_sees_rejected(client, users_and_keys):
    r = client.get("/claims", params={"project_id": 1}, headers=_h(users_and_keys["consumer"]["key"]))
    for item in r.json()["items"]:
        assert item["corroboration_level"] != "rejected"


def test_consumer_sees_disputed_claims(client, users_and_keys):
    r = client.get("/claims", params={"project_id": 1}, headers=_h(users_and_keys["consumer"]["key"]))
    disputed = [i for i in r.json()["items"] if i.get("dispute_state") == "disputed"]
    assert len(disputed) >= 1, "disputed claims with public sensitivity should be visible to consumer"


def test_employee_sees_only_own_claims(client, users_and_keys):
    r = client.get("/claims", params={"project_id": 1}, headers=_h(users_and_keys["employee"]["key"]))
    items = r.json()["items"]
    eid = users_and_keys["employee"]["uid"]
    for item in items:
        if item["evidence_text"].startswith("TS_"):
            assert item["evidence_text"] == "TS_employee_claim", \
                f"employee sees non-own claim: {item['evidence_text']}"


def test_curator_sees_all_including_draft_rejected(client, users_and_keys):
    r = client.get("/claims", params={"project_id": 1}, headers=_h(users_and_keys["curator"]["key"]))
    texts = {i["evidence_text"] for i in r.json()["items"]}
    assert "TS_draft_claim" in texts, "curator must see drafts"
    assert "TS_rejected_claim" in texts, "curator must see rejected"
    assert "TS_restricted_validated" in texts, "curator must see restricted"


def test_filter_by_corroboration_level(client, users_and_keys):
    r = client.get("/claims", params={"project_id": 1, "corroboration_level": "draft"},
                   headers=_h(users_and_keys["curator"]["key"]))
    for item in r.json()["items"]:
        assert item["corroboration_level"] == "draft"


def test_filter_by_dispute_state(client, users_and_keys):
    r = client.get("/claims", params={"project_id": 1, "dispute_state": "disputed"},
                   headers=_h(users_and_keys["curator"]["key"]))
    items = r.json()["items"]
    for item in items:
        assert item["dispute_state"] == "disputed"
    assert len(items) >= 1
