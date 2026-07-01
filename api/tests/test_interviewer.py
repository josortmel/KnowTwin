"""P1.13 Interviewer tests — state machine, novelty, convergence, checkpointing.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_interviewer.py -v
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

_DB_URL = os.environ["DATABASE_URL"]
_PREFIX = "ivtest_"
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
    """Create test employee + interview session."""
    async def _setup():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval(
                "INSERT INTO users (name) VALUES ($1) RETURNING id", f"{_PREFIX}employee"
            )
            await conn.execute(
                "INSERT INTO user_emails (email, user_id, is_primary) VALUES ($1, $2, true)",
                f"{_PREFIX}employee@test.kt", uid,
            )
            await conn.execute(
                "INSERT INTO project_members (project_id, user_id, role) VALUES ($1, $2, 'employee')",
                _PID, uid,
            )
            await conn.execute(
                "INSERT INTO entity_expected_claims "
                "(project_id, entity_name, entity_type, expected_count, expected_criticality) "
                "VALUES ($1, $2, 'cliente_cuenta', 10, 0.9) "
                "ON CONFLICT (project_id, entity_name) DO NOTHING",
                _PID, f"{_PREFIX}CriticalClient",
            )
            await conn.execute(
                "INSERT INTO nodes (name, type, status) VALUES ($1, 'cliente_cuenta', 'active') "
                "ON CONFLICT (name) DO NOTHING",
                f"{_PREFIX}CriticalClient",
            )
            return uid
        finally:
            await conn.close()

    _run(_setup())
    yield

    async def _teardown():
        conn = await asyncpg.connect(_DB_URL)
        try:
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


def _create_session():
    """Create an interview session, return (session_id, employee_id)."""
    async def _do():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}employee")
            sid = await conn.fetchval(
                "INSERT INTO interview_sessions (project_id, employee_id, topic, status) "
                "VALUES ($1, $2, $3, 'in_progress') RETURNING id",
                _PID, uid, f"{_PREFIX}test_topic",
            )
            return str(sid), uid
        finally:
            await conn.close()
    return _run(_do())


def test_prepare_dossier_loads_entities():
    """prepare_dossier loads entity_expected_claims into state."""
    from interviewer import InterviewState, prepare_dossier

    sid, uid = _create_session()

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            state = InterviewState(sid, _PID, uid)
            state = await prepare_dossier(conn, state)
            assert state.state == "open_topic"
            assert len(state.dossier_entities) > 0
        finally:
            await conn.close()
    _run(_test())


def test_novelty_new_entity():
    """New entity → novelty 1.0."""
    from interviewer import _compute_novelty

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            n = await _compute_novelty(conn, _PID, f"{_PREFIX}BrandNew", "manages", "team")
            assert n == 1.0
        finally:
            await conn.close()
    _run(_test())


def test_novelty_contradiction():
    """Same subject+predicate, different value → novelty 0.8."""
    from interviewer import _compute_novelty

    uid = _run(_dbval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}employee"))
    _run(_db(
        "INSERT INTO claims (user_id, project_id, subject_entity, predicate, object_value, "
        "evidence_text, source_type, corroboration_level, sensitivity) "
        "VALUES ($1, $2, $3, 'sla', '4h', 'existing claim', 'document', 'single_source', 'public')",
        uid, _PID, f"{_PREFIX}ContraEntity",
    ))

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            n = await _compute_novelty(conn, _PID, f"{_PREFIX}ContraEntity", "sla", "2h")
            assert n == 0.8
        finally:
            await conn.close()
    _run(_test())


def test_convergence_detection():
    """turn_value < 0.15 for 2 consecutive → converged."""
    from interviewer import InterviewState, _check_convergence

    state = InterviewState("fake", 1, 1)
    state.turn_values = [0.5, 0.3, 0.1, 0.05]
    assert _check_convergence(state) is True

    state.turn_values = [0.5, 0.3, 0.1, 0.2]
    assert _check_convergence(state) is False

    state.turn_values = [0.1]
    assert _check_convergence(state) is False


def test_criticality_from_expected_claims():
    """Criticality comes from entity_expected_claims, not claims table."""
    from interviewer import _get_entity_criticality

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            crit = await _get_entity_criticality(conn, _PID, f"{_PREFIX}CriticalClient")
            assert abs(crit - 0.9) < 0.01
            unknown = await _get_entity_criticality(conn, _PID, "nonexistent_entity_xyz")
            assert unknown == 0.5
        finally:
            await conn.close()
    _run(_test())


def test_state_persistence():
    """State saved and loaded correctly (checkpointing)."""
    from interviewer import InterviewState, save_state, load_state

    sid, uid = _create_session()

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            state = InterviewState(sid, _PID, uid)
            state.state = "conduct"
            state.turn_count = 3
            state.current_topic = "TestTopic"
            state.turn_values = [0.5, 0.3, 0.1]
            await save_state(conn, state)

            loaded = await load_state(conn, sid)
            assert loaded is not None
            assert loaded.state == "conduct"
            assert loaded.turn_count == 3
            assert loaded.current_topic == "TestTopic"
            assert loaded.turn_values == [0.5, 0.3, 0.1]
        finally:
            await conn.close()
    _run(_test())


def test_employee_id_from_session():
    """Interview claims use employee_id from session, not caller."""
    from interviewer import InterviewState

    sid, uid = _create_session()
    state = InterviewState(sid, _PID, uid)
    assert state.employee_id == uid
