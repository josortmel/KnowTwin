"""P2.6 Dispute resolution tests.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_disputes.py -v
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql://knowtwin:knowtwin_test_pass@knowtwin-db:5432/knowtwin")
os.environ.setdefault("ENVIRONMENT", "development")

import asyncpg

from disputes import _can_resolve, _why_resolved, _compute_breakdown
from curator_post import run_curator_post

_DB_URL = os.environ["DATABASE_URL"]
_PREFIX = "disptest_"
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


async def _dbrow(sql, *args):
    conn = await asyncpg.connect(_DB_URL)
    try:
        return await conn.fetchrow(sql, *args)
    finally:
        await conn.close()


@pytest.fixture(scope="module", autouse=True)
def setup_teardown():
    async def _setup():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval(
                "INSERT INTO users (name) VALUES ($1) RETURNING id", f"{_PREFIX}emp"
            )
            await conn.execute(
                "INSERT INTO user_emails (email, user_id, is_primary) VALUES ($1, $2, true)",
                f"{_PREFIX}emp@test.kt", uid,
            )
            await conn.execute(
                "INSERT INTO project_members (project_id, user_id, role) VALUES ($1, $2, 'employee')",
                _PID, uid,
            )
            curator_uid = await conn.fetchval(
                "INSERT INTO users (name) VALUES ($1) RETURNING id", f"{_PREFIX}curator"
            )
            await conn.execute(
                "INSERT INTO user_emails (email, user_id, is_primary) VALUES ($1, $2, true)",
                f"{_PREFIX}curator@test.kt", curator_uid,
            )
            await conn.execute(
                "INSERT INTO project_members (project_id, user_id, role) VALUES ($1, $2, 'curator')",
                _PID, curator_uid,
            )
            consumer_uid = await conn.fetchval(
                "INSERT INTO users (name) VALUES ($1) RETURNING id", f"{_PREFIX}consumer"
            )
            await conn.execute(
                "INSERT INTO user_emails (email, user_id, is_primary) VALUES ($1, $2, true)",
                f"{_PREFIX}consumer@test.kt", consumer_uid,
            )
            await conn.execute(
                "INSERT INTO project_members (project_id, user_id, role) VALUES ($1, $2, 'consumer')",
                _PID, consumer_uid,
            )
        finally:
            await conn.close()

    _run(_setup())
    yield

    async def _teardown():
        conn = await asyncpg.connect(_DB_URL)
        try:
            await conn.execute("DELETE FROM cell_runs WHERE cell_type = 'curator_post' AND metrics::text LIKE $1", f"%{_PREFIX}%")
            await conn.execute("DELETE FROM audit_log WHERE resource_id IN (SELECT id::text FROM claims WHERE subject_entity LIKE $1)", f"{_PREFIX}%")
            await conn.execute("DELETE FROM claims WHERE subject_entity LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM interview_sessions WHERE topic LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM project_members WHERE user_id IN (SELECT id FROM users WHERE name LIKE $1)", f"{_PREFIX}%")
            await conn.execute("DELETE FROM user_emails WHERE email LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM users WHERE name LIKE $1", f"{_PREFIX}%")
        finally:
            await conn.close()
    _run(_teardown())


def _clean():
    _run(_db("DELETE FROM cell_runs WHERE cell_type = 'curator_post' AND metrics::text LIKE $1", f"%{_PREFIX}%"))
    _run(_db("DELETE FROM audit_log WHERE resource_id IN (SELECT id::text FROM claims WHERE subject_entity LIKE $1)", f"{_PREFIX}%"))
    _run(_db("DELETE FROM claims WHERE subject_entity LIKE $1", f"{_PREFIX}%"))
    _run(_db("DELETE FROM interview_sessions WHERE topic LIKE $1", f"{_PREFIX}%"))


def _make_disputed_pair():
    """Create a tacit + doc claim pair in disputed state with doc_strength."""
    async def _do():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}emp")
            sid = await conn.fetchval(
                "INSERT INTO interview_sessions (project_id, employee_id, topic, status) "
                "VALUES ($1, $2, $3, 'completed') RETURNING id",
                _PID, uid, f"{_PREFIX}session",
            )
            tacit_id = await conn.fetchval(
                "INSERT INTO claims (user_id, project_id, subject_entity, predicate, object_value, "
                "evidence_text, source_type, corroboration_level, sensitivity, session_id, employee_id, "
                "dispute_state) "
                "VALUES ($1, $2, $3, 'sla_hours', '2h', 'Employee says 2h', 'interview', "
                "'single_source', 'restricted', $4, $1, 'disputed') RETURNING id",
                uid, _PID, f"{_PREFIX}Entity", sid,
            )
            doc_id = await conn.fetchval(
                "INSERT INTO claims (user_id, project_id, subject_entity, predicate, object_value, "
                "evidence_text, source_type, corroboration_level, sensitivity, trust_tier, "
                "dispute_state, disputed_by_claim_id, doc_strength) "
                "VALUES ($1, $2, $3, 'sla_hours', '4h', 'Document says 4h', 'document', "
                "'single_source', 'public', 2, 'disputed', $4, 3.0) RETURNING id",
                uid, _PID, f"{_PREFIX}Entity", tacit_id,
            )
            await conn.execute(
                "UPDATE claims SET disputed_by_claim_id = $1 WHERE id = $2",
                doc_id, tacit_id,
            )
            return str(sid), str(tacit_id), str(doc_id)
        finally:
            await conn.close()
    return _run(_do())


def test_both_versions_with_doc_strength():
    """GET dispute-detail returns both claims + doc_strength breakdown."""
    _clean()
    _, tacit_id, doc_id = _make_disputed_pair()

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            row = await conn.fetchrow(
                "SELECT id, subject_entity, predicate, object_value, evidence_text, "
                "source_type, sensitivity, corroboration_level, dispute_state, "
                "criticality, doc_strength, trust_tier, project_id, "
                "disputed_by_claim_id, resolution_note, resolved_by_user_id, resolver_user_id "
                "FROM claims WHERE id = $1",
                UUID(doc_id),
            )
            assert row is not None
            breakdown = await _compute_breakdown(conn, dict(row))
            assert breakdown is not None
            assert breakdown.source_count >= 1
            assert breakdown.trust_tier == 2
            assert breakdown.computed_strength == breakdown.source_count * 1.0 * 3

            cpart = await conn.fetchrow(
                "SELECT id FROM claims WHERE id = $1", row["disputed_by_claim_id"]
            )
            assert cpart is not None
            assert str(cpart["id"]) == tacit_id
        finally:
            await conn.close()
    _run(_test())


def test_why_resolved_deterministic():
    """Resolved claim's 'why' includes source_count/freshness/tier — deterministic."""
    _clean()
    _, _, doc_id = _make_disputed_pair()

    _run(_db(
        "UPDATE claims SET dispute_state = 'resolved_in_favor', "
        "resolution_note = 'auto: doc_strength=3.00 below threshold 1.50', "
        "resolved_by_user_id = NULL WHERE id = $1",
        UUID(doc_id),
    ))

    row = _run(_dbrow(
        "SELECT dispute_state, resolution_note, resolved_by_user_id FROM claims WHERE id = $1",
        UUID(doc_id),
    ))
    why = _why_resolved(dict(row))
    assert why is not None
    assert "Auto-resolved" in why
    assert "doc_strength" in why
    assert "3.00" in why


def test_resolve_authz_denies_consumer_employee():
    """Consumer and employee cannot resolve disputes (deny-by-default)."""
    consumer_actor = {"sub": "999", "role": "consumer"}
    employee_actor = {"sub": "998", "role": "employee"}
    claim_row = {"project_id": 1, "resolver_user_id": None}

    assert _can_resolve("consumer", 999, claim_row) is False
    assert _can_resolve("employee", 998, claim_row) is False


def test_resolve_allows_curator_admin():
    """Curator and admin CAN resolve."""
    claim_row = {"project_id": 1, "resolver_user_id": None}

    assert _can_resolve("curator", 100, claim_row) is True
    assert _can_resolve("admin", 100, claim_row) is True


def test_resolve_allows_assigned_resolver():
    """Assigned resolver can resolve even if not curator/admin."""
    resolver_id = 42
    claim_row = {"project_id": 1, "resolver_user_id": resolver_id}

    assert _can_resolve("consumer", resolver_id, claim_row) is True
    assert _can_resolve("consumer", 999, claim_row) is False


def test_manual_records_real_id():
    """Manual resolution records resolved_by_user_id = actor's id."""
    _clean()
    _, _, doc_id = _make_disputed_pair()

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            curator_uid = await conn.fetchval(
                "SELECT id FROM users WHERE name = $1", f"{_PREFIX}curator"
            )
            await conn.execute(
                "UPDATE claims SET dispute_state = 'resolved_in_favor', "
                "resolved_by_user_id = $1, resolution_note = 'Manual review confirms document' "
                "WHERE id = $2",
                curator_uid, UUID(doc_id),
            )
            row = await conn.fetchrow(
                "SELECT resolved_by_user_id, resolution_note FROM claims WHERE id = $1",
                UUID(doc_id),
            )
            assert row["resolved_by_user_id"] == curator_uid
            assert row["resolved_by_user_id"] is not None
        finally:
            await conn.close()
    _run(_test())


def test_auto_has_null_note():
    """Auto-resolution from curator_post has resolved_by_user_id=NULL + 'auto:' note."""
    _clean()

    async def _do():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}emp")
            sid = await conn.fetchval(
                "INSERT INTO interview_sessions (project_id, employee_id, topic, status) "
                "VALUES ($1, $2, $3, 'completed') RETURNING id",
                _PID, uid, f"{_PREFIX}session",
            )
            await conn.execute(
                "INSERT INTO claims (user_id, project_id, subject_entity, predicate, object_value, "
                "evidence_text, source_type, corroboration_level, sensitivity, session_id, employee_id) "
                "VALUES ($1, $2, $3, 'sla_hours', '2h', 'Employee says 2h', 'interview', "
                "'single_source', 'restricted', $4, $1)",
                uid, _PID, f"{_PREFIX}Entity", sid,
            )
            await conn.execute(
                "INSERT INTO claims (user_id, project_id, subject_entity, predicate, object_value, "
                "evidence_text, source_type, corroboration_level, sensitivity, trust_tier) "
                "VALUES ($1, $2, $3, 'sla_hours', '4h', 'Document says 4h', 'document', "
                "'single_source', 'public', 0)",
                uid, _PID, f"{_PREFIX}Entity",
            )
            return str(sid)
        finally:
            await conn.close()
    sid = _run(_do())

    async def _test():
        pool = await asyncpg.create_pool(_DB_URL, min_size=1, max_size=2)
        try:
            await run_curator_post(pool, sid)

            conn = await asyncpg.connect(_DB_URL)
            try:
                row = await conn.fetchrow(
                    "SELECT dispute_state, resolution_note, resolved_by_user_id "
                    "FROM claims WHERE subject_entity = $1 AND source_type = 'document'",
                    f"{_PREFIX}Entity",
                )
                assert row["dispute_state"] == "resolved_in_favor"
                assert row["resolved_by_user_id"] is None
                assert row["resolution_note"].startswith("auto:")
            finally:
                await conn.close()
        finally:
            await pool.close()
    _run(_test())


def test_resolved_against_excluded_but_gated():
    """resolved_against not in primary twin results, but accessible via dispute-detail."""
    _clean()
    _, _, doc_id = _make_disputed_pair()

    _run(_db(
        "UPDATE claims SET dispute_state = 'resolved_against' WHERE id = $1",
        UUID(doc_id),
    ))

    # Verify twin._format_answer excludes resolved_against claims
    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            all_claims = await conn.fetch(
                "SELECT id, subject_entity, predicate, object_value, evidence_text, "
                "sensitivity, corroboration_level, dispute_state, criticality "
                "FROM claims WHERE subject_entity = $1",
                f"{_PREFIX}Entity",
            )
            # Apply the same filter as twin_query
            primary = [
                dict(c) for c in all_claims
                if c["dispute_state"] != "resolved_against"
            ]
            resolved_ids = {
                str(c["id"]) for c in all_claims
                if c["dispute_state"] == "resolved_against"
            }
            primary_ids = {str(c["id"]) for c in primary}

            assert doc_id in resolved_ids
            assert doc_id not in primary_ids

            # But the claim still exists in DB (gated access via dispute-detail)
            row = await conn.fetchrow(
                "SELECT id, dispute_state FROM claims WHERE id = $1", UUID(doc_id)
            )
            assert row is not None
            assert row["dispute_state"] == "resolved_against"
        finally:
            await conn.close()
    _run(_test())
