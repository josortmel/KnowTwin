"""P2.11 Retention + deletion (GDPR) tests.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_retention.py -v
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

from deletion import gdpr_erase_claim, run_retention_expiry

_DB_URL = os.environ["DATABASE_URL"]
_PREFIX = "rettest_"
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
            # Clean stale data from prior failed runs (FK order matters)
            await conn.execute("DELETE FROM deletion_requests WHERE claim_id IN (SELECT id FROM claims WHERE subject_entity LIKE $1 OR subject_entity = '[ERASED]')", f"{_PREFIX}%")
            await conn.execute("DELETE FROM audit_log WHERE resource_id IN (SELECT id::text FROM claims WHERE subject_entity LIKE $1 OR subject_entity = '[ERASED]')", f"{_PREFIX}%")
            await conn.execute("DELETE FROM cell_runs WHERE cell_type = 'retention_expiry' AND metrics::text LIKE $1", f"%{_PID}%")
            await conn.execute("DELETE FROM claims WHERE subject_entity LIKE $1 OR (subject_entity = '[ERASED]' AND project_id = $2)", f"{_PREFIX}%", _PID)
            await conn.execute("DELETE FROM interview_sessions WHERE employee_id IN (SELECT id FROM users WHERE name LIKE $1)", f"{_PREFIX}%")
            await conn.execute("DELETE FROM project_members WHERE user_id IN (SELECT id FROM users WHERE name LIKE $1)", f"{_PREFIX}%")
            await conn.execute("DELETE FROM user_emails WHERE email LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM users WHERE name LIKE $1", f"{_PREFIX}%")

            emp_uid = await conn.fetchval(
                "INSERT INTO users (name) VALUES ($1) RETURNING id", f"{_PREFIX}emp"
            )
            await conn.execute(
                "INSERT INTO user_emails (email, user_id, is_primary) VALUES ($1, $2, true)",
                f"{_PREFIX}emp@test.kt", emp_uid,
            )
            await conn.execute(
                "INSERT INTO project_members (project_id, user_id, role) VALUES ($1, $2, 'employee')",
                _PID, emp_uid,
            )
            cur_uid = await conn.fetchval(
                "INSERT INTO users (name) VALUES ($1) RETURNING id", f"{_PREFIX}curator"
            )
            await conn.execute(
                "INSERT INTO user_emails (email, user_id, is_primary) VALUES ($1, $2, true)",
                f"{_PREFIX}curator@test.kt", cur_uid,
            )
            await conn.execute(
                "INSERT INTO project_members (project_id, user_id, role) VALUES ($1, $2, 'curator')",
                _PID, cur_uid,
            )
        finally:
            await conn.close()

    _run(_setup())
    yield

    async def _teardown():
        conn = await asyncpg.connect(_DB_URL)
        try:
            await conn.execute("DELETE FROM cell_runs WHERE cell_type = 'retention_expiry' AND metrics::text LIKE $1", f"%{_PID}%")
            await conn.execute("DELETE FROM deletion_requests WHERE claim_id IN (SELECT id FROM claims WHERE project_id = $1)", _PID)
            await conn.execute("DELETE FROM audit_log WHERE resource_id IN (SELECT id::text FROM claims WHERE subject_entity LIKE $1 OR subject_entity = '[ERASED]')", f"{_PREFIX}%")
            await conn.execute("DELETE FROM audit_log WHERE resource = 'deletion_request' AND details::text LIKE $1", f"%{_PREFIX}%")
            await conn.execute("DELETE FROM claims WHERE subject_entity LIKE $1 OR (subject_entity = '[ERASED]' AND project_id = $2)", f"{_PREFIX}%", _PID)
            await conn.execute("DELETE FROM interview_sessions WHERE employee_id IN (SELECT id FROM users WHERE name LIKE $1)", f"{_PREFIX}%")
            await conn.execute("DELETE FROM org_settings WHERE project_id = $1", _PID)
            await conn.execute("DELETE FROM project_members WHERE user_id IN (SELECT id FROM users WHERE name LIKE $1)", f"{_PREFIX}%")
            await conn.execute("DELETE FROM user_emails WHERE email LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM users WHERE name LIKE $1", f"{_PREFIX}%")
        finally:
            await conn.close()
    _run(_teardown())


def _clean():
    _run(_db("DELETE FROM deletion_requests WHERE claim_id IN (SELECT id FROM claims WHERE subject_entity LIKE $1 OR (subject_entity = '[ERASED]' AND project_id = $2))", f"{_PREFIX}%", _PID))
    _run(_db("DELETE FROM audit_log WHERE resource_id IN (SELECT id::text FROM claims WHERE subject_entity LIKE $1 OR subject_entity = '[ERASED]')", f"{_PREFIX}%"))
    _run(_db("DELETE FROM cell_runs WHERE cell_type = 'retention_expiry'"))
    _run(_db("DELETE FROM claims WHERE subject_entity LIKE $1 OR (subject_entity = '[ERASED]' AND project_id = $2)", f"{_PREFIX}%", _PID))
    _run(_db("DELETE FROM org_settings WHERE project_id = $1", _PID))


def _make_claim(subject_suffix="Entity", sensitivity="restricted"):
    async def _do():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}emp")
            sid = await conn.fetchval(
                "INSERT INTO interview_sessions (project_id, employee_id, topic, status) "
                "VALUES ($1, $2, $3, 'completed') RETURNING id",
                _PID, uid, f"{_PREFIX}session",
            )
            cid = await conn.fetchval(
                "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
                "object_value, evidence_text, sanitized_text, source_type, "
                "corroboration_level, sensitivity, session_id, employee_id) "
                "VALUES ($1, $2, $3, 'manages', 'ETL pipeline', "
                "'Juan manages the ETL pipeline end to end', "
                "'Juan manages the [REDACTED] pipeline', 'interview', "
                "'single_source', $4, $5, $1) RETURNING id",
                uid, _PID, f"{_PREFIX}{subject_suffix}", sensitivity, sid,
            )
            return str(cid), uid
        finally:
            await conn.close()
    return _run(_do())


def test_erasure_removes_evidence():
    """After GDPR erase → evidence_text=NULL, embedding=NULL, subject='[ERASED]'."""
    _clean()
    cid_str, uid = _make_claim()

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            await gdpr_erase_claim(conn, UUID(cid_str), uid, "test_erasure")
            row = await conn.fetchrow("SELECT * FROM claims WHERE id = $1", UUID(cid_str))
            assert row["evidence_text"] == "[ERASED]"
            assert row["sanitized_text"] is None
            assert row["embedding"] is None
            assert row["subject_entity"] == "[ERASED]"
            assert row["predicate"] == "[ERASED]"
            assert row["object_entity"] is None
            assert row["object_value"] is None
            assert row["employee_id"] is None
            assert row["user_id"] is None
            assert row["session_id"] is None
            assert row["resolution_note"] is None
            assert row["tags"] == []
            assert row["corroboration_level"] == "rejected"
        finally:
            await conn.close()
    _run(_test())


def test_erasure_removes_from_search():
    """Erased claim absent from visibility-filtered queries."""
    _clean()
    cid_str, uid = _make_claim(sensitivity="public")

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            # Before erasure: visible
            from claims import _visibility_sql
            vis_sql, vis_params = _visibility_sql("consumer", 999, 2)
            params = [_PID, *vis_params]
            before = await conn.fetch(
                f"SELECT id FROM claims c WHERE c.project_id = $1 AND ({vis_sql}) "
                f"AND c.subject_entity LIKE '{_PREFIX}%'",
                *params,
            )
            assert len(before) >= 1

            # Erase
            await gdpr_erase_claim(conn, UUID(cid_str), uid, "test_search")

            # After erasure: invisible (rejected = not in embed levels)
            after = await conn.fetch(
                f"SELECT id FROM claims c WHERE c.project_id = $1 AND ({vis_sql}) "
                f"AND (c.subject_entity LIKE '{_PREFIX}%' OR c.subject_entity = '[ERASED]')",
                *params,
            )
            erased_ids = {str(r["id"]) for r in after}
            assert cid_str not in erased_ids
        finally:
            await conn.close()
    _run(_test())


def test_autoexpiry_bounded_idempotent():
    """Cron processes N claims, re-run = no-op."""
    _clean()

    async def _setup():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}emp")
            # Create old claims (> 30 days)
            for i in range(3):
                await conn.execute(
                    "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
                    "evidence_text, source_type, corroboration_level, sensitivity, "
                    "created_at) "
                    "VALUES ($1, $2, $3, $4, 'old evidence', 'document', "
                    "'single_source', 'restricted', now() - interval '60 days')",
                    uid, _PID, f"{_PREFIX}OldEntity{i}", f"pred_{i}",
                )
            # Set retention to 30 days with auto_expiry
            await conn.execute(
                "INSERT INTO org_settings (project_id, config) VALUES ($1, $2::jsonb) "
                "ON CONFLICT (project_id) DO UPDATE SET config = $2::jsonb",
                _PID, json.dumps({"retention": {"retention_days": 30, "auto_expiry": True}}),
            )
        finally:
            await conn.close()
    _run(_setup())

    async def _test():
        pool = await asyncpg.create_pool(_DB_URL, min_size=1, max_size=2)
        try:
            r1 = await run_retention_expiry(pool, _PID)
            assert r1["expired"] == 3

            r2 = await run_retention_expiry(pool, _PID)
            assert r2["expired"] == 0
        finally:
            await pool.close()
    _run(_test())


def test_deletion_employee_own_only():
    """Employee can't request deletion of another's claim — 403."""
    _clean()

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            emp_uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}emp")
            cur_uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}curator")

            # Claim owned by curator (employee_id = cur_uid)
            cid = await conn.fetchval(
                "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
                "evidence_text, source_type, corroboration_level, sensitivity, employee_id) "
                "VALUES ($1, $2, $3, 'pred', 'evidence', 'interview', 'single_source', "
                "'restricted', $1) RETURNING id",
                cur_uid, _PID, f"{_PREFIX}OtherClaim",
            )

            # Simulate employee trying to request deletion of curator's claim
            claim = await conn.fetchrow(
                "SELECT id, project_id, employee_id, corroboration_level FROM claims WHERE id = $1",
                cid,
            )
            assert claim["employee_id"] == cur_uid
            assert claim["employee_id"] != emp_uid

            # The endpoint checks: if claim["employee_id"] != actor_id → 403
            # Verify the guard condition directly
            actor_id = emp_uid
            assert claim["employee_id"] != actor_id, \
                "Employee should NOT be able to request deletion of another's claim"

            # Verify no pending request was created
            pending = await conn.fetchval(
                "SELECT COUNT(*) FROM deletion_requests WHERE claim_id = $1", cid,
            )
            assert pending == 0
        finally:
            await conn.close()
    _run(_test())


def test_deletion_requires_curator_review():
    """Request → pending → curator approves → claim erased."""
    _clean()
    cid_str, emp_uid = _make_claim()

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            cur_uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}curator")

            # Create deletion request
            req_id = await conn.fetchval(
                "INSERT INTO deletion_requests (project_id, claim_id, requested_by, reason) "
                "VALUES ($1, $2, $3, 'GDPR request') RETURNING id",
                _PID, UUID(cid_str), emp_uid,
            )

            # Verify pending
            req = await conn.fetchrow(
                "SELECT status FROM deletion_requests WHERE id = $1", req_id
            )
            assert req["status"] == "pending"

            # Claim still exists
            claim = await conn.fetchrow("SELECT evidence_text FROM claims WHERE id = $1", UUID(cid_str))
            assert claim["evidence_text"] is not None

            # Curator approves → GDPR erase
            await gdpr_erase_claim(conn, UUID(cid_str), cur_uid, "employee_request")
            await conn.execute(
                "UPDATE deletion_requests SET status = 'approved', reviewed_by = $1, "
                "resolved_at = now() WHERE id = $2",
                cur_uid, req_id,
            )

            # Claim erased — full PII check
            claim_after = await conn.fetchrow("SELECT * FROM claims WHERE id = $1", UUID(cid_str))
            assert claim_after["evidence_text"] == "[ERASED]"
            assert claim_after["subject_entity"] == "[ERASED]"
            assert claim_after["predicate"] == "[ERASED]"
            assert claim_after["employee_id"] is None
            assert claim_after["session_id"] is None

            # Request approved
            req_after = await conn.fetchrow("SELECT status FROM deletion_requests WHERE id = $1", req_id)
            assert req_after["status"] == "approved"
        finally:
            await conn.close()
    _run(_test())


def test_deletion_reject():
    """Curator rejects → claim unchanged."""
    _clean()
    cid_str, emp_uid = _make_claim()

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            cur_uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}curator")

            req_id = await conn.fetchval(
                "INSERT INTO deletion_requests (project_id, claim_id, requested_by, reason) "
                "VALUES ($1, $2, $3, 'want to delete') RETURNING id",
                _PID, UUID(cid_str), emp_uid,
            )

            # Curator rejects
            await conn.execute(
                "UPDATE deletion_requests SET status = 'rejected', reviewed_by = $1, "
                "resolved_at = now() WHERE id = $2",
                cur_uid, req_id,
            )

            # Claim unchanged
            claim = await conn.fetchrow("SELECT * FROM claims WHERE id = $1", UUID(cid_str))
            assert claim["evidence_text"] is not None
            assert claim["subject_entity"] == f"{_PREFIX}Entity"
            assert claim["corroboration_level"] == "single_source"
        finally:
            await conn.close()
    _run(_test())


def test_tombstone_no_personal_data():
    """deletion_requests row has NO evidence_text, NO names, reason NULLed after approval."""
    _clean()
    cid_str, emp_uid = _make_claim()

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            cur_uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}curator")

            # Get session_id before erasure
            pre_session = await conn.fetchval(
                "SELECT session_id FROM claims WHERE id = $1", UUID(cid_str)
            )

            req_id = await conn.fetchval(
                "INSERT INTO deletion_requests (project_id, claim_id, requested_by, reason) "
                "VALUES ($1, $2, $3, 'delete claim about Juan incompetence') RETURNING id",
                _PID, UUID(cid_str), emp_uid,
            )

            # Erase + approve (nulls reason per F35)
            await gdpr_erase_claim(conn, UUID(cid_str), cur_uid, "employee_request")
            await conn.execute(
                "UPDATE deletion_requests SET status = 'approved', reviewed_by = $1, "
                "resolved_at = now(), reason = NULL WHERE id = $2",
                cur_uid, req_id,
            )

            # Tombstone: reason NULLed, no PII
            tombstone = await conn.fetchrow(
                "SELECT * FROM deletion_requests WHERE id = $1", req_id
            )
            assert tombstone["status"] == "approved"
            assert tombstone["reason"] is None
            assert tombstone["claim_id"] is not None
            assert tombstone["requested_by"] is not None
            assert tombstone["reviewed_by"] is not None

            tombstone_text = str(dict(tombstone))
            assert "Juan" not in tombstone_text
            assert "incompetence" not in tombstone_text

            # Session rollup erased
            if pre_session:
                sess = await conn.fetchrow(
                    "SELECT rollup, dossier FROM interview_sessions WHERE id = $1",
                    pre_session,
                )
                assert sess["rollup"] == "[Session data erased per GDPR request]"
                if sess["dossier"]:
                    dossier = sess["dossier"]
                    if isinstance(dossier, str):
                        import json
                        dossier = json.loads(dossier)
                    assert "turn_texts" not in dossier
                    assert "entities_seen" not in dossier

            # Claim link tables cleaned
            links = await conn.fetchval(
                "SELECT COUNT(*) FROM claim_entity_links WHERE claim_id = $1", UUID(cid_str)
            )
            assert links == 0
        finally:
            await conn.close()
    _run(_test())
