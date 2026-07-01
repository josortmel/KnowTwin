"""EG1-EG7: embed gate tests against REAL knowtwin-tei.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_embed_gate.py -v

Requires: knowtwin-tei running (GPU), knowtwin-db healthy.
"""
import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql://knowtwin:knowtwin_test_pass@knowtwin-db:5432/knowtwin")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("EMBEDDINGS_URL", "http://knowtwin-tei:8090")

import asyncpg
from fastapi.testclient import TestClient

from main import create_app
from auth import generate_api_key

_DB_URL = os.environ["DATABASE_URL"]


@pytest.fixture(scope="module")
def app():
    return create_app("development")


@pytest.fixture(scope="module")
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def api_key():
    key_plain, key_hash = generate_api_key()
    loop = asyncio.new_event_loop()

    async def _setup():
        conn = await asyncpg.connect(_DB_URL)
        try:
            await conn.execute(
                "INSERT INTO api_keys (key_hash, name, user_id, active) "
                "VALUES ($1, 'test-eg', 1, true)",
                key_hash,
            )
        finally:
            await conn.close()

    loop.run_until_complete(_setup())
    yield key_plain

    async def _teardown():
        conn = await asyncpg.connect(_DB_URL)
        try:
            await conn.execute("DELETE FROM api_keys WHERE name = 'test-eg'")
        finally:
            await conn.close()

    loop.run_until_complete(_teardown())
    loop.close()


def _auth(key):
    return {"Authorization": f"Bearer {key}"}


def _create_claim(client, key, **overrides):
    payload = {
        "subject_entity": "TestEntity",
        "predicate": "sabe",
        "evidence_text": "Test evidence for embed gate verification",
        "source_type": "curator",
        "project_id": 1,
    }
    payload.update(overrides)
    r = client.post("/claims", json=payload, headers=_auth(key))
    assert r.status_code == 201, r.text
    return r.json()


def _db_fetch(sql, *args):
    loop = asyncio.new_event_loop()

    async def _q():
        conn = await asyncpg.connect(_DB_URL)
        try:
            return await conn.fetchrow(sql, *args)
        finally:
            await conn.close()

    result = loop.run_until_complete(_q())
    loop.close()
    return result


def _db_val(sql, *args):
    loop = asyncio.new_event_loop()

    async def _q():
        conn = await asyncpg.connect(_DB_URL)
        try:
            return await conn.fetchval(sql, *args)
        finally:
            await conn.close()

    result = loop.run_until_complete(_q())
    loop.close()
    return result


def _db_exec(sql, *args):
    loop = asyncio.new_event_loop()

    async def _q():
        conn = await asyncpg.connect(_DB_URL)
        try:
            return await conn.execute(sql, *args)
        finally:
            await conn.close()

    loop.run_until_complete(_q())
    loop.close()


# -- Cleanup fixture --

@pytest.fixture(autouse=True)
def _cleanup_test_claims():
    yield
    _db_exec("DELETE FROM claims WHERE evidence_text LIKE 'Test evidence%'")


# -- EG1: draft → no embed --

def test_eg1_draft_no_embed(client, api_key):
    claim = _create_claim(client, api_key)
    assert claim["corroboration_level"] == "draft"
    assert claim["has_embedding"] is False

    row = _db_fetch("SELECT embedding FROM claims WHERE id = $1", UUID(claim["id"]))
    assert row["embedding"] is None


# -- EG2: promote(single_source) → embedding NOT NULL, dims=512 --

def test_eg2_promote_single_source_embeds(client, api_key):
    claim = _create_claim(client, api_key)

    r = client.put(
        f"/claims/{claim['id']}/promote",
        json={"new_level": "single_source"},
        headers=_auth(api_key),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["corroboration_level"] == "single_source"
    assert data["has_embedding"] is True

    dims = _db_val(
        "SELECT vector_dims(embedding) FROM claims WHERE id = $1", UUID(claim["id"])
    )
    assert dims == 512


# -- EG3: rejected → embedding removed, row retained (tombstone) --

def test_eg3_rejected_clears_embedding(client, api_key):
    claim = _create_claim(client, api_key)

    client.put(
        f"/claims/{claim['id']}/promote",
        json={"new_level": "single_source"},
        headers=_auth(api_key),
    )

    r = client.put(
        f"/claims/{claim['id']}/promote",
        json={"new_level": "rejected"},
        headers=_auth(api_key),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["corroboration_level"] == "rejected"
    assert data["has_embedding"] is False

    row = _db_fetch(
        "SELECT embedding, id FROM claims WHERE id = $1", UUID(claim["id"])
    )
    assert row is not None, "claim row should be retained (tombstone)"
    assert row["embedding"] is None


# -- EG4: disputed → embedding present --

def test_eg4_disputed_keeps_embedding(client, api_key):
    claim = _create_claim(client, api_key)

    client.put(
        f"/claims/{claim['id']}/promote",
        json={"new_level": "single_source"},
        headers=_auth(api_key),
    )

    _db_exec(
        "UPDATE claims SET dispute_state = 'disputed' WHERE id = $1",
        UUID(claim["id"]),
    )

    row = _db_fetch(
        "SELECT embedding, dispute_state, corroboration_level FROM claims WHERE id = $1",
        UUID(claim["id"]),
    )
    assert row["dispute_state"] == "disputed"
    assert row["embedding"] is not None


# -- EG5: chunk upload → 0 chunks with embedding --

def test_eg5_no_chunk_embeddings(client, api_key):
    count = _db_val("SELECT count(*) FROM document_chunks WHERE embedding IS NOT NULL")
    assert count == 0, f"expected 0 chunks with embedding, got {count}"


# -- EG6: draft + disputed → NULL (axes independent) --

def test_eg6_draft_disputed_no_embed(client, api_key):
    claim = _create_claim(client, api_key)

    _db_exec(
        "UPDATE claims SET dispute_state = 'disputed' WHERE id = $1",
        UUID(claim["id"]),
    )

    row = _db_fetch(
        "SELECT embedding, dispute_state, corroboration_level FROM claims WHERE id = $1",
        UUID(claim["id"]),
    )
    assert row["corroboration_level"] == "draft"
    assert row["dispute_state"] == "disputed"
    assert row["embedding"] is None


# -- EG7: promote → reject → re-promote never leaves stale embedding --

def test_eg7_promote_reject_no_stale(client, api_key):
    claim = _create_claim(client, api_key)

    client.put(
        f"/claims/{claim['id']}/promote",
        json={"new_level": "single_source"},
        headers=_auth(api_key),
    )

    emb_before = _db_val(
        "SELECT embedding FROM claims WHERE id = $1", UUID(claim["id"])
    )
    assert emb_before is not None

    client.put(
        f"/claims/{claim['id']}/promote",
        json={"new_level": "rejected"},
        headers=_auth(api_key),
    )

    emb_after = _db_val(
        "SELECT embedding FROM claims WHERE id = $1", UUID(claim["id"])
    )
    assert emb_after is None, "embedding must be NULL after rejection"

    r = client.put(
        f"/claims/{claim['id']}/promote",
        json={"new_level": "single_source"},
        headers=_auth(api_key),
    )
    assert r.status_code == 409, "re-promote from rejected must be blocked (terminal)"

    emb_final = _db_val(
        "SELECT embedding FROM claims WHERE id = $1", UUID(claim["id"])
    )
    assert emb_final is None, "embedding must remain NULL after blocked re-promote"


# -- Audit SQL (run after all tests) --

def test_audit_gate_invariant(client, api_key):
    chunks_with_embed = _db_val(
        "SELECT count(*) FROM document_chunks WHERE embedding IS NOT NULL"
    )
    assert chunks_with_embed == 0, f"AUDIT FAIL: {chunks_with_embed} chunks have embeddings"

    violators = _db_val("""
        SELECT count(*) FROM claims
        WHERE (embedding IS NOT NULL AND corroboration_level NOT IN
               ('single_source','corroborated','corroborated_by_employee','validated'))
           OR (embedding IS NULL AND corroboration_level IN
               ('single_source','corroborated','corroborated_by_employee','validated'))
    """)
    assert violators == 0, f"AUDIT FAIL: {violators} claims violate gate invariant"
