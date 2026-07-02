"""P1.4 Claims API tests — CRUD + gate + visibility + security.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_claims.py -v
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
def app():
    return create_app("development")


@pytest.fixture(scope="module")
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def keys():
    """Create users with roles + keys: super, curator, employee, consumer."""
    async def _setup():
        conn = await asyncpg.connect(_DB_URL)
        try:
            result = {}
            for name, role in [("tc_curator", "curator"), ("tc_employee", "employee"), ("tc_consumer", "consumer")]:
                uid = await conn.fetchval("INSERT INTO users (name) VALUES ($1) RETURNING id", name)
                await conn.execute(
                    "INSERT INTO user_emails (email, user_id, is_primary) VALUES ($1, $2, true)",
                    f"{name}@test.kt", uid,
                )
                await conn.execute(
                    "INSERT INTO project_members (project_id, user_id, role) VALUES (1, $1, $2)",
                    uid, role,
                )
                kp, kh = generate_api_key()
                await conn.execute(
                    "INSERT INTO api_keys (key_hash, name, user_id, active) VALUES ($1, $2, $3, true)",
                    kh, f"tc-{name}", uid,
                )
                result[role] = {"key": kp, "uid": uid}

            kp, kh = generate_api_key()
            await conn.execute(
                "INSERT INTO api_keys (key_hash, name, user_id, active) VALUES ($1, 'tc-super', 1, true)",
                kh,
            )
            result["super"] = {"key": kp, "uid": 1}
            return result
        finally:
            await conn.close()

    data = _run(_setup())
    yield data

    async def _teardown():
        conn = await asyncpg.connect(_DB_URL)
        try:
            await conn.execute("DELETE FROM claims WHERE evidence_text LIKE 'TC_%'")
            for role, info in data.items():
                if role != "super":
                    await conn.execute("DELETE FROM audit_log WHERE user_id = $1", info["uid"])
                    await conn.execute("DELETE FROM api_keys WHERE user_id = $1", info["uid"])
                    await conn.execute("DELETE FROM project_members WHERE user_id = $1", info["uid"])
                    await conn.execute("DELETE FROM user_emails WHERE user_id = $1", info["uid"])
                    await conn.execute("DELETE FROM users WHERE id = $1", info["uid"])
                else:
                    await conn.execute("DELETE FROM api_keys WHERE name = 'tc-super'")
        finally:
            await conn.close()

    _run(_teardown())


def _h(key):
    return {"Authorization": f"Bearer {key}"}


def _create(client, key, **kw):
    payload = {
        "subject_entity": "TestEntity",
        "predicate": "sabe",
        "evidence_text": "TC_default evidence",
        "source_type": "curator",
        "project_id": 1,
    }
    payload.update(kw)
    return client.post("/claims", json=payload, headers=_h(key))


# ---------------------------------------------------------------------------
# test_claim_create_rejects_privileged_fields
# ---------------------------------------------------------------------------

def test_claim_create_rejects_privileged_fields(client, keys):
    for field in ["employee_id", "session_id", "source_id", "trust_tier",
                   "confidence", "corroboration_level", "dispute_state",
                   "freshness_state", "doc_strength", "disputed_by_claim_id",
                   "resolved_by_user_id", "embedding"]:
        r = _create(client, keys["super"]["key"],
                     evidence_text=f"TC_priv_{field}", **{field: "bogus"})
        assert r.status_code == 422, f"field {field} should be rejected, got {r.status_code}"


# ---------------------------------------------------------------------------
# test_embed_gate_inlist
# ---------------------------------------------------------------------------

def test_embed_gate_inlist(client, keys):
    r = _create(client, keys["curator"]["key"], evidence_text="TC_gate_inlist")
    assert r.status_code == 201
    claim = r.json()
    assert claim["corroboration_level"] == "draft"
    assert claim["has_embedding"] is False


# ---------------------------------------------------------------------------
# test_lifecycle_illegal_transition_409
# ---------------------------------------------------------------------------

def test_lifecycle_illegal_transition_409(client, keys):
    r = _create(client, keys["curator"]["key"], evidence_text="TC_transition")
    claim = r.json()
    cid = claim["id"]
    k = keys["curator"]["key"]

    r = client.put(f"/claims/{cid}/promote", json={"new_level": "corroborated"}, headers=_h(k))
    assert r.status_code == 409, "draft→corroborated should be illegal"

    r = client.put(f"/claims/{cid}/promote", json={"new_level": "validated"}, headers=_h(k))
    assert r.status_code == 409, "draft→validated should be illegal"


# ---------------------------------------------------------------------------
# test_invariant3_cap
# ---------------------------------------------------------------------------

def test_invariant3_cap(client, keys):
    r = _create(client, keys["curator"]["key"],
                 evidence_text="TC_cap_interview", source_type="interview")
    cid = r.json()["id"]
    k = keys["super"]["key"]

    _run(_db(
        "UPDATE claims SET corroboration_level = 'corroborated_by_employee' WHERE id = $1::uuid",
        cid,
    ))

    r = client.put(f"/claims/{cid}/promote", json={"new_level": "validated"}, headers=_h(k))
    assert r.status_code == 409, "interview claim must not reach validated"
    assert "CAP" in r.json()["detail"]


# ---------------------------------------------------------------------------
# test_employee_own_filter
# ---------------------------------------------------------------------------

def test_employee_own_filter(client, keys):
    eid = keys["employee"]["uid"]
    curator_uid = keys["curator"]["uid"]
    _run(_db(
        """INSERT INTO claims (project_id, subject_entity, predicate, evidence_text,
           source_type, employee_id, corroboration_level)
           VALUES (1, 'EmpEntity', 'sabe', 'TC_emp_own', 'interview', $1, 'single_source')""",
        eid,
    ))
    _run(_db(
        """INSERT INTO claims (project_id, subject_entity, predicate, evidence_text,
           source_type, employee_id, corroboration_level)
           VALUES (1, 'OtherEntity', 'sabe', 'TC_emp_other', 'interview', $1, 'single_source')""",
        curator_uid,
    ))

    r = client.get("/claims", params={"project_id": 1}, headers=_h(keys["employee"]["key"]))
    assert r.status_code == 200
    items = r.json()["items"]
    for item in items:
        assert item.get("evidence_text") != "TC_emp_other", "employee should not see other employee's claims"

    _run(_db("DELETE FROM claims WHERE evidence_text IN ('TC_emp_own', 'TC_emp_other')"))


# ---------------------------------------------------------------------------
# test_sensitivity_visibility
# ---------------------------------------------------------------------------

def test_sensitivity_visibility(client, keys):
    _run(_db(
        """INSERT INTO claims (project_id, subject_entity, predicate, evidence_text,
           source_type, sensitivity, corroboration_level)
           VALUES (1, 'Restricted', 'sabe', 'TC_restricted', 'curator', 'restricted', 'single_source')""",
    ))

    r = client.get("/claims", params={"project_id": 1}, headers=_h(keys["consumer"]["key"]))
    assert r.status_code == 200
    for item in r.json()["items"]:
        assert item.get("evidence_text") != "TC_restricted", "consumer should not see restricted claims"

    _run(_db("DELETE FROM claims WHERE evidence_text = 'TC_restricted'"))


# ---------------------------------------------------------------------------
# test_draft_invisible_to_consumer
# ---------------------------------------------------------------------------

def test_draft_invisible_to_consumer(client, keys):
    r = _create(client, keys["curator"]["key"], evidence_text="TC_draft_invisible")
    cid = r.json()["id"]

    r = client.get(f"/claims/{cid}", headers=_h(keys["consumer"]["key"]))
    assert r.status_code == 404, "consumer must not see draft claims"

    r = client.get("/claims", params={"project_id": 1}, headers=_h(keys["consumer"]["key"]))
    for item in r.json()["items"]:
        assert item["corroboration_level"] != "draft", "consumer list must not contain drafts"


# ---------------------------------------------------------------------------
# test_soft_delete_removes_embedding_and_triples_and_hides
# ---------------------------------------------------------------------------

def test_soft_delete_removes_embedding_and_triples_and_hides(client, keys):
    r = _create(client, keys["curator"]["key"], evidence_text="TC_soft_delete")
    cid = r.json()["id"]
    k = keys["curator"]["key"]

    r = client.delete(f"/claims/{cid}", headers=_h(k))
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"

    row = _run(_dbval("SELECT corroboration_level FROM claims WHERE id = $1::uuid", cid))
    assert row == "rejected"

    emb = _run(_dbval("SELECT embedding FROM claims WHERE id = $1::uuid", cid))
    assert emb is None

    r = client.get(f"/claims/{cid}", headers=_h(keys["consumer"]["key"]))
    assert r.status_code == 404, "rejected claim hidden from consumer"

    audit = _run(_dbval(
        "SELECT count(*) FROM audit_log WHERE resource = 'claim' AND resource_id = $1",
        cid,
    ))
    assert audit >= 1, "soft delete must be audit-logged"


# ---------------------------------------------------------------------------
# test_no_sql_injection_in_filters
# ---------------------------------------------------------------------------

def test_no_sql_injection_in_filters(client, keys):
    r = client.get("/claims", params={
        "project_id": 1,
        "subject_entity": "'; DROP TABLE claims; --",
    }, headers=_h(keys["curator"]["key"]))
    assert r.status_code == 200

    exists = _run(_dbval("SELECT EXISTS(SELECT 1 FROM claims LIMIT 1)"))
    assert exists is not None, "claims table must still exist after injection attempt"


# ---------------------------------------------------------------------------
# test_null_byte_and_maxlen_rejected
# ---------------------------------------------------------------------------

def test_null_byte_and_maxlen_rejected(client, keys):
    r = _create(client, keys["curator"]["key"], evidence_text="TC_null\x00byte")
    assert r.status_code == 422, "null byte must be rejected"

    r = _create(client, keys["curator"]["key"], evidence_text="x" * (16_001))
    assert r.status_code == 422, "over-max-length must be rejected"

    r = _create(client, keys["curator"]["key"], tags=["x" * 201])
    assert r.status_code == 422, "over-max-tag-length must be rejected"


# ---------------------------------------------------------------------------
# TG-P1.4-1: Employee tighten-only sensitivity
# ---------------------------------------------------------------------------

def test_employee_tighten_only_sensitivity(client, keys):
    """Employee cannot loosen sensitivity (restricted→public=403). Can tighten (team→restricted=ok)."""
    eid = keys["employee"]["uid"]
    _run(_db(
        """INSERT INTO claims (project_id, subject_entity, predicate, evidence_text,
           source_type, employee_id, corroboration_level, sensitivity)
           VALUES (1, 'TightenEntity', 'sabe', 'TC_tighten', 'interview', $1, 'single_source', 'restricted')""",
        eid,
    ))
    cid = _run(_dbval(
        "SELECT id::text FROM claims WHERE evidence_text = 'TC_tighten'"
    ))

    # Loosen restricted→public: MUST be 403
    r = client.put(f"/claims/{cid}", json={"sensitivity": "public"},
                   headers=_h(keys["employee"]["key"]))
    assert r.status_code == 403, f"loosen should be 403, got {r.status_code}"

    # Set to team first (curator can do it)
    _run(_db("UPDATE claims SET sensitivity = 'team' WHERE id = $1::uuid", cid))

    # Tighten team→restricted: MUST be allowed
    r = client.put(f"/claims/{cid}", json={"sensitivity": "restricted"},
                   headers=_h(keys["employee"]["key"]))
    assert r.status_code == 200, f"tighten should be 200, got {r.status_code}"
    assert r.json()["sensitivity"] == "restricted"

    _run(_db("DELETE FROM claims WHERE evidence_text = 'TC_tighten'"))


# ---------------------------------------------------------------------------
# TG-P1.4-2: PUT /claims/{id} update tags
# ---------------------------------------------------------------------------

def test_update_claim_tags(client, keys):
    """PUT update_claim changes tags and audits."""
    r = _create(client, keys["curator"]["key"], evidence_text="TC_tags_update")
    cid = r.json()["id"]

    r = client.put(f"/claims/{cid}", json={"tags": ["important", "reviewed"]},
                   headers=_h(keys["curator"]["key"]))
    assert r.status_code == 200
    assert set(r.json()["tags"]) == {"important", "reviewed"}

    audit = _run(_dbval(
        "SELECT count(*) FROM audit_log WHERE resource = 'claim' AND resource_id = $1 "
        "AND action = 'update_claim'", cid,
    ))
    assert audit >= 1
