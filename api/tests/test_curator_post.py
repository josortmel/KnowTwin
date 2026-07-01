"""P1.11 Curator post-session tests — doc_strength, auto-resolution, sanitization.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_curator_post.py -v
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

from curator_post import compute_doc_strength, sanitize_evidence, run_curator_post

_DB_URL = os.environ["DATABASE_URL"]
_PREFIX = "cptest_"
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


def _make_session_and_claims(tacit_val, doc_val, doc_trust_tier=0):
    """Create a session with one tacit claim and one documentary claim on same predicate."""
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
                "VALUES ($1, $2, $3, 'sla_hours', $4, 'Employee says ' || $4, 'interview', "
                "'single_source', 'restricted', $5, $1)",
                uid, _PID, f"{_PREFIX}Entity", tacit_val, sid,
            )
            await conn.execute(
                "INSERT INTO claims (user_id, project_id, subject_entity, predicate, object_value, "
                "evidence_text, source_type, corroboration_level, sensitivity, trust_tier) "
                "VALUES ($1, $2, $3, 'sla_hours', $4, 'Document says ' || $4, 'document', "
                "'single_source', 'public', $5)",
                uid, _PID, f"{_PREFIX}Entity", doc_val, doc_trust_tier,
            )
            return str(sid)
        finally:
            await conn.close()
    return _run(_do())


def test_doc_strength_formula():
    """doc_strength = source_count × freshness × (trust_tier+1)."""
    assert compute_doc_strength(1, 1.0, 0) == 1.0
    assert compute_doc_strength(1, 1.0, 2) == 3.0
    assert compute_doc_strength(2, 0.5, 1) == 2.0


def test_docstrength_weak_autoresolves():
    """Weak doc (tier=0, 1 source) → auto-resolve in favor of tacit."""
    _run(_db("DELETE FROM claims WHERE subject_entity = $1", f"{_PREFIX}Entity"))
    _run(_db("DELETE FROM interview_sessions WHERE topic LIKE $1", f"{_PREFIX}%"))
    _run(_db("DELETE FROM cell_runs WHERE cell_type = 'curator_post' AND metrics::text LIKE $1", f"%{_PREFIX}%"))

    sid = _make_session_and_claims("2h", "4h", doc_trust_tier=0)

    async def _test():
        pool = await asyncpg.create_pool(_DB_URL, min_size=1, max_size=2)
        try:
            result = await run_curator_post(pool, sid)
            assert result["auto_resolved"] >= 1
        finally:
            await pool.close()
    _run(_test())

    state = _run(_dbval(
        "SELECT dispute_state FROM claims WHERE subject_entity = $1 AND source_type = 'document'",
        f"{_PREFIX}Entity",
    ))
    assert state == "resolved_in_favor"


def test_docstrength_strong_disputed():
    """Strong doc (tier=2, 1 source → strength=3.0) → disputed."""
    _run(_db("DELETE FROM claims WHERE subject_entity = $1", f"{_PREFIX}Entity"))
    _run(_db("DELETE FROM interview_sessions WHERE topic LIKE $1", f"{_PREFIX}%"))
    _run(_db("DELETE FROM cell_runs WHERE cell_type = 'curator_post' AND metrics::text LIKE $1", f"%{_PREFIX}%"))

    sid = _make_session_and_claims("2h", "4h", doc_trust_tier=2)

    async def _test():
        pool = await asyncpg.create_pool(_DB_URL, min_size=1, max_size=2)
        try:
            result = await run_curator_post(pool, sid)
            assert result["disputed"] >= 1
        finally:
            await pool.close()
    _run(_test())

    state = _run(_dbval(
        "SELECT dispute_state FROM claims WHERE subject_entity = $1 AND source_type = 'document'",
        f"{_PREFIX}Entity",
    ))
    assert state == "disputed"


def test_sanitization_removes_judgment():
    """Judgment words removed from evidence_text."""
    text = "Juan is incompetent and stupid, but Elena manages the account"
    cleaned, modified = sanitize_evidence(text)
    assert modified is True
    assert "incompetent" not in cleaned
    assert "stupid" not in cleaned
    assert "Elena" in cleaned
    assert "manages" in cleaned


def test_idempotent_per_session():
    """Second run on same session_id returns already_completed."""
    _run(_db("DELETE FROM claims WHERE subject_entity = $1", f"{_PREFIX}Entity"))
    _run(_db("DELETE FROM interview_sessions WHERE topic LIKE $1", f"{_PREFIX}%"))
    _run(_db("DELETE FROM cell_runs WHERE cell_type = 'curator_post' AND metrics::text LIKE $1", f"%{_PREFIX}%"))

    sid = _make_session_and_claims("same", "same", doc_trust_tier=0)

    async def _test():
        pool = await asyncpg.create_pool(_DB_URL, min_size=1, max_size=2)
        try:
            r1 = await run_curator_post(pool, sid)
            assert "error" not in r1
            r2 = await run_curator_post(pool, sid)
            assert r2.get("error") == "already_completed"
        finally:
            await pool.close()
    _run(_test())
