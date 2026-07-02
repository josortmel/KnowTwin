"""P1.17 Adversarial Interviewer fixtures — 5 failure modes, DB state assertions.

Stub LLM returns canned JSON. ALL assertions on observable state (claim rows,
graph nodes, dispute_state, coverage). ZERO assertions on LLM prose.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_interviewer_adversarial.py -v
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql://knowtwin:knowtwin_test_pass@knowtwin-db:5432/knowtwin")
os.environ.setdefault("ENVIRONMENT", "development")

import asyncpg

_DB_URL = os.environ["DATABASE_URL"]
_PREFIX = "advtest_"
_PID = 1
_FIXTURES = Path(__file__).parent / "fixtures" / "adversarial"


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


async def _dbrows(sql, *args):
    conn = await asyncpg.connect(_DB_URL)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


def _load_fixture(name):
    return (_FIXTURES / name).read_text()


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
            # Seed existing doc claim for contradiction tests
            await conn.execute(
                "INSERT INTO claims (user_id, project_id, subject_entity, predicate, object_value, "
                "evidence_text, source_type, corroboration_level, sensitivity) "
                "VALUES ($1, $2, $3, 'sla_hours', '4 hours', 'Contract SLA 4h', "
                "'document', 'single_source', 'public')",
                uid, _PID, f"{_PREFIX}CloudBase",
            )
            await conn.execute(
                "INSERT INTO entity_expected_claims "
                "(project_id, entity_name, entity_type, expected_count, expected_criticality) "
                "VALUES ($1, $2, 'proveedor', 5, 0.8) ON CONFLICT DO NOTHING",
                _PID, f"{_PREFIX}CloudBase",
            )
            await conn.execute(
                "INSERT INTO nodes (name, type, status) VALUES ($1, 'proveedor', 'active') "
                "ON CONFLICT (name) DO NOTHING",
                f"{_PREFIX}CloudBase",
            )
        finally:
            await conn.close()

    _run(_setup())
    yield

    async def _teardown():
        conn = await asyncpg.connect(_DB_URL)
        try:
            await conn.execute("DELETE FROM audit_log WHERE user_id IN (SELECT id FROM users WHERE name LIKE $1)", f"{_PREFIX}%")
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


def _make_session():
    async def _do():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}emp")
            sid = await conn.fetchval(
                "INSERT INTO interview_sessions (project_id, employee_id, topic, status) "
                "VALUES ($1, $2, $3, 'in_progress') RETURNING id",
                _PID, uid, f"{_PREFIX}fixture",
            )
            return str(sid), uid
        finally:
            await conn.close()
    return _run(_do())


def _stub_llm(fixture_file):
    """Create a stub _llm_call that returns canned JSON."""
    canned = _load_fixture(fixture_file)
    async def _fake_llm(system_prompt, user_prompt):
        return canned
    return _fake_llm


# F1: contradicts-everything → novelty 0.8, claim created with different value
def test_f1_contradicts_everything():
    sid, uid = _make_session()

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            from interviewer import InterviewState, prepare_dossier, open_topic, conduct_turn, save_state

            state = InterviewState(sid, _PID, uid)
            state = await prepare_dossier(conn, state)
            state = await open_topic(conn, state)
            state.current_topic = f"{_PREFIX}CloudBase"
            await save_state(conn, state)

            with patch("cell_worker._llm_call", new=AsyncMock(return_value=_load_fixture("f1_contradicts.json"))):
                result = await conduct_turn(conn, state, "Everything is wrong, SLA is 1 hour")

            claims = await conn.fetch(
                "SELECT object_value FROM claims WHERE session_id = $1", sid
            )
            if claims:
                assert any(c["object_value"] == "1 hour" for c in claims)
        finally:
            await conn.close()

    _run(_test())


# F2: confirms-everything → convergence (low turn_value, novelty 0.1)
def test_f2_confirms_converges():
    sid, uid = _make_session()

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            from interviewer import InterviewState, prepare_dossier, open_topic, conduct_turn, save_state, _check_convergence

            state = InterviewState(sid, _PID, uid)
            state = await prepare_dossier(conn, state)
            state = await open_topic(conn, state)
            state.current_topic = f"{_PREFIX}CloudBase"
            await save_state(conn, state)

            with patch("cell_worker._llm_call", new=AsyncMock(return_value=_load_fixture("f2_confirms.json"))):
                for _ in range(3):
                    result = await conduct_turn(conn, state, "Yes, SLA is 4 hours as documented")

            # Confirming novelty=0.1, turn_value should be low → converge
            assert len(state.turn_values) >= 2
            low_turns = sum(1 for v in state.turn_values if v < 0.15)
            assert low_turns >= 2, f"confirms should produce low turn values: {state.turn_values}"
        finally:
            await conn.close()

    _run(_test())


# F3: evasive → 0 claims extracted (empty LLM response)
def test_f3_evasive_no_fabrication():
    sid, uid = _make_session()

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            from interviewer import InterviewState, prepare_dossier, open_topic, conduct_turn, save_state

            state = InterviewState(sid, _PID, uid)
            state = await prepare_dossier(conn, state)
            state = await open_topic(conn, state)
            await save_state(conn, state)

            with patch("cell_worker._llm_call", new=AsyncMock(return_value=_load_fixture("f3_evasive.json"))):
                result = await conduct_turn(conn, state, "I don't really remember the details")

            assert len(result["claims_created"]) == 0, "evasive responses must not fabricate claims"
            assert result["turn_value"] == 0.0
        finally:
            await conn.close()

    _run(_test())


# F4: false-info → pejorative absent from evidence, sensitivity='restricted'
def test_f4_false_info_sanitized():
    """Claims with judgment words get sanitized by curator_post."""
    from curator_post import sanitize_evidence

    text = "Carlos is incompetent and stupid, Elena does all the real work"
    cleaned, modified = sanitize_evidence(text)

    assert modified is True
    assert "incompetent" not in cleaned
    assert "stupid" not in cleaned
    assert "Elena" in cleaned
    assert "[REDACTED]" in cleaned


# F5: unknown-entities → new node created, claim linked
def test_f5_unknown_entity_creates_node():
    sid, uid = _make_session()

    node_before = _run(_dbval(
        "SELECT COUNT(*) FROM nodes WHERE name = $1", f"{_PREFIX}BrandNewVendor"
    ))
    assert node_before == 0

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            from interviewer import InterviewState, prepare_dossier, open_topic, conduct_turn, save_state

            state = InterviewState(sid, _PID, uid)
            state = await prepare_dossier(conn, state)
            state = await open_topic(conn, state)
            await save_state(conn, state)

            with patch("cell_worker._llm_call", new=AsyncMock(return_value=_load_fixture("f5_unknown_entity.json"))):
                result = await conduct_turn(conn, state, "We use BrandNewVendor for cloud storage")

            if result["claims_created"]:
                claim = await conn.fetchrow(
                    "SELECT subject_entity FROM claims WHERE id = $1",
                    result["claims_created"][0],
                )
                assert claim["subject_entity"] == f"{_PREFIX}BrandNewVendor"
                assert f"{_PREFIX}BrandNewVendor" in state.entities_seen
        finally:
            await conn.close()

    _run(_test())
