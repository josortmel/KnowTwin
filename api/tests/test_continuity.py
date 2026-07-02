"""P2.7 Interview continuity (multi-session) tests.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_continuity.py -v
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql://knowtwin:knowtwin_test_pass@knowtwin-db:5432/knowtwin")
os.environ.setdefault("ENVIRONMENT", "development")

import asyncpg

from interviewer import InterviewState, prepare_dossier, open_topic, _compute_novelty
from dossier import regenerate_dossier

_DB_URL = os.environ["DATABASE_URL"]
_PREFIX = "cttest_"
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
            for name, etype, expected, crit in [
                (f"{_PREFIX}GapEntity", "person", 5, 0.9),
                (f"{_PREFIX}ClearEntity", "process", 2, 0.7),
                (f"{_PREFIX}OpenEntity", "system", 4, 0.5),
            ]:
                await conn.execute(
                    "INSERT INTO nodes (name, type) VALUES ($1, $2) ON CONFLICT (name) DO NOTHING",
                    name, etype,
                )
                await conn.execute(
                    "INSERT INTO entity_expected_claims (project_id, entity_name, entity_type, "
                    "expected_count, expected_criticality) "
                    "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (project_id, entity_name) DO NOTHING",
                    _PID, name, etype, expected, crit,
                )
        finally:
            await conn.close()

    _run(_setup())
    yield

    async def _teardown():
        conn = await asyncpg.connect(_DB_URL)
        try:
            await conn.execute("DELETE FROM cell_runs WHERE cell_type = 'dossier_regen' AND metrics::text LIKE $1", f"%{_PREFIX}%")
            await conn.execute("DELETE FROM cell_runs WHERE cell_type = 'curator_post' AND metrics::text LIKE $1", f"%{_PREFIX}%")
            await conn.execute("DELETE FROM audit_log WHERE resource_id IN (SELECT id::text FROM claims WHERE subject_entity LIKE $1)", f"{_PREFIX}%")
            await conn.execute("DELETE FROM claims WHERE subject_entity LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM interview_sessions WHERE topic LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM entity_expected_claims WHERE entity_name LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM nodes WHERE name LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM project_members WHERE user_id IN (SELECT id FROM users WHERE name LIKE $1)", f"{_PREFIX}%")
            await conn.execute("DELETE FROM user_emails WHERE email LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM users WHERE name LIKE $1", f"{_PREFIX}%")
        finally:
            await conn.close()
    _run(_teardown())


def _clean():
    _run(_db("DELETE FROM cell_runs WHERE cell_type IN ('dossier_regen','curator_post') AND metrics::text LIKE $1", f"%{_PREFIX}%"))
    _run(_db("DELETE FROM audit_log WHERE resource_id IN (SELECT id::text FROM claims WHERE subject_entity LIKE $1)", f"{_PREFIX}%"))
    _run(_db("DELETE FROM claims WHERE subject_entity LIKE $1", f"{_PREFIX}%"))
    _run(_db("DELETE FROM interview_sessions WHERE topic LIKE $1", f"{_PREFIX}%"))


def _make_session1():
    """Create completed session1 with claims on GapEntity, then regenerate dossier."""
    async def _do():
        pool = await asyncpg.create_pool(_DB_URL, min_size=1, max_size=2)
        try:
            conn = await pool.acquire()
            try:
                uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}emp")
                sid = await conn.fetchval(
                    "INSERT INTO interview_sessions (project_id, employee_id, topic, status, completed_at) "
                    "VALUES ($1, $2, $3, 'completed', now()) RETURNING id",
                    _PID, uid, f"{_PREFIX}session1",
                )
                # Claims on GapEntity (partial coverage)
                await conn.execute(
                    "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
                    "object_value, evidence_text, source_type, corroboration_level, "
                    "sensitivity, session_id, employee_id, criticality) "
                    "VALUES ($1, $2, $3, 'manages_process', 'yes', 'Employee says yes', "
                    "'interview', 'single_source', 'restricted', $4, $1, 0.9)",
                    uid, _PID, f"{_PREFIX}GapEntity", sid,
                )
                # Flood ClearEntity to reach 'clear' coverage
                for pred in ("task_a", "task_b", "task_c"):
                    await conn.execute(
                        "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
                        "object_value, evidence_text, source_type, corroboration_level, "
                        "sensitivity, session_id, employee_id, criticality) "
                        "VALUES ($1, $2, $3, $4, 'done', 'documented', 'interview', "
                        "'single_source', 'restricted', $5, $1, 0.7)",
                        uid, _PID, f"{_PREFIX}ClearEntity", pred, sid,
                    )
            finally:
                await pool.release(conn)

            # Regenerate dossier after session1
            await regenerate_dossier(pool, str(sid))
            return str(sid), uid
        finally:
            await pool.close()
    return _run(_do())


def test_ct1_session2_references_session1():
    """CT1: session2 prepare_dossier references session1 data (open_threads, gaps)."""
    _clean()
    sid1, uid = _make_session1()

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            sid2 = await conn.fetchval(
                "INSERT INTO interview_sessions (project_id, employee_id, topic, status) "
                "VALUES ($1, $2, $3, 'scheduled') RETURNING id",
                _PID, uid, f"{_PREFIX}session2",
            )
            state = InterviewState(str(sid2), _PID, uid)
            state = await prepare_dossier(conn, state)

            assert state.prior_session_id == sid1
            assert len(state.prior_open_threads) > 0
            assert state.state == "open_topic"
        finally:
            await conn.close()
    _run(_test())


def test_ct2_unclosed_gap_reopened():
    """CT2: unclosed gap from session1 reopened in session2 topic selection."""
    _clean()
    sid1, uid = _make_session1()

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            sid2 = await conn.fetchval(
                "INSERT INTO interview_sessions (project_id, employee_id, topic, status) "
                "VALUES ($1, $2, $3, 'scheduled') RETURNING id",
                _PID, uid, f"{_PREFIX}session2",
            )
            state = InterviewState(str(sid2), _PID, uid)
            state = await prepare_dossier(conn, state)
            state = await open_topic(conn, state)

            assert state.state == "conduct"
            assert state.current_topic is not None
            # GapEntity or OpenEntity should be selected (both have gaps)
            gap_entities = {f"{_PREFIX}GapEntity", f"{_PREFIX}OpenEntity"}
            assert state.current_topic in gap_entities
        finally:
            await conn.close()
    _run(_test())


def test_ct3_cumulative_novelty():
    """CT3: claim confirming prior session's claim gets novelty=0.1 (not 1.0)."""
    _clean()
    sid1, uid = _make_session1()

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            # Session1 created a claim for GapEntity.manages_process = 'yes'
            # Computing novelty for same subject/predicate/value should return 0.1
            novelty = await _compute_novelty(
                conn, _PID, f"{_PREFIX}GapEntity", "manages_process", "yes"
            )
            assert novelty == 0.1

            # New predicate for same entity should return 1.0
            novelty_new = await _compute_novelty(
                conn, _PID, f"{_PREFIX}GapEntity", "new_predicate", "something"
            )
            assert novelty_new == 1.0

            # Contradicting value should return 0.8
            novelty_contra = await _compute_novelty(
                conn, _PID, f"{_PREFIX}GapEntity", "manages_process", "no"
            )
            assert novelty_contra == 0.8
        finally:
            await conn.close()
    _run(_test())


def test_ct4_clear_entity_not_reopened():
    """CT4: closed gap (entity at 'clear') NOT reopened in session2."""
    _clean()
    sid1, uid = _make_session1()

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            # Verify ClearEntity is indeed at 'clear' coverage
            cov = await conn.fetchrow(
                "SELECT coverage_state FROM entity_coverage "
                "WHERE project_id = $1 AND entity_name = $2",
                _PID, f"{_PREFIX}ClearEntity",
            )
            # ClearEntity has 3 claims, expected=2, crit=0.7
            # coverage = (3*0.7) / (2*0.7) * 100 = 150% → 'clear'
            assert cov is not None and cov["coverage_state"] == "clear", \
                f"ClearEntity should be at 'clear' coverage, got {cov}"

            sid2 = await conn.fetchval(
                "INSERT INTO interview_sessions (project_id, employee_id, topic, status) "
                "VALUES ($1, $2, $3, 'scheduled') RETURNING id",
                _PID, uid, f"{_PREFIX}session2",
            )
            state = InterviewState(str(sid2), _PID, uid)
            state = await prepare_dossier(conn, state)
            assert state.prior_session_id is not None

            # Iterate all topics — ClearEntity should never be selected
            selected_topics = []
            for _ in range(len(state.dossier_entities)):
                state = await open_topic(conn, state)
                if state.state == "write_rollup":
                    break
                selected_topics.append(state.current_topic)
                state.topics_covered.append(state.current_topic)

            assert f"{_PREFIX}ClearEntity" not in selected_topics
        finally:
            await conn.close()
    _run(_test())
