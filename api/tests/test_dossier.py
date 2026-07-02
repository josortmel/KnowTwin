"""P2.2 Dossier regeneration tests.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_dossier.py -v
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

from dossier import regenerate_dossier
from interviewer import InterviewState, prepare_dossier

_DB_URL = os.environ["DATABASE_URL"]
_PREFIX = "dstest_"
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
            for name, etype, expected, crit in [
                (f"{_PREFIX}EntityA", "person", 5, 0.9),
                (f"{_PREFIX}EntityB", "process", 3, 0.7),
                (f"{_PREFIX}EntityC", "system", 2, 0.3),
            ]:
                await conn.execute(
                    "INSERT INTO nodes (name, type) VALUES ($1, $2) ON CONFLICT (name) DO NOTHING",
                    name, etype,
                )
                await conn.execute(
                    "INSERT INTO entity_expected_claims (project_id, entity_name, entity_type, expected_count, expected_criticality) "
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
    """Remove test data between tests."""
    _run(_db("DELETE FROM cell_runs WHERE cell_type IN ('dossier_regen','curator_post') AND metrics::text LIKE $1", f"%{_PREFIX}%"))
    _run(_db("DELETE FROM audit_log WHERE resource_id IN (SELECT id::text FROM claims WHERE subject_entity LIKE $1)", f"{_PREFIX}%"))
    _run(_db("DELETE FROM claims WHERE subject_entity LIKE $1", f"{_PREFIX}%"))
    _run(_db("DELETE FROM interview_sessions WHERE topic LIKE $1", f"{_PREFIX}%"))


def _make_session_with_claims():
    """Create a completed session with claims on EntityA and EntityB."""
    async def _do():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}emp")
            sid = await conn.fetchval(
                "INSERT INTO interview_sessions (project_id, employee_id, topic, status, completed_at) "
                "VALUES ($1, $2, $3, 'completed', now()) RETURNING id",
                _PID, uid, f"{_PREFIX}session",
            )
            # Claims on EntityA (2 claims → partial coverage)
            for pred in ("manages_process", "knows_tool"):
                await conn.execute(
                    "INSERT INTO claims (user_id, project_id, subject_entity, predicate, object_value, "
                    "evidence_text, source_type, corroboration_level, sensitivity, session_id, "
                    "employee_id, criticality) "
                    "VALUES ($1, $2, $3, $4, 'yes', 'Employee says yes', 'interview', "
                    "'single_source', 'restricted', $5, $1, 0.9)",
                    uid, _PID, f"{_PREFIX}EntityA", pred, sid,
                )
            # No claims on EntityB or EntityC → they stay 'unknown'
            return str(sid), uid
        finally:
            await conn.close()
    return _run(_do())


def test_ds1_coverage_after_dossier_regen():
    """DS1: After dossier_regen, coverage_snapshot reflects claims from session."""
    _clean()
    sid, _ = _make_session_with_claims()

    async def _test():
        pool = await asyncpg.create_pool(_DB_URL, min_size=1, max_size=2)
        try:
            result = await regenerate_dossier(pool, sid)
            assert "error" not in result
            assert result["coverage_entities"] > 0

            row = await pool.fetchrow(
                "SELECT dossier FROM interview_sessions WHERE id = $1", sid
            )
            dossier = row["dossier"]
            if isinstance(dossier, str):
                dossier = json.loads(dossier)
            regen = dossier["regenerated_dossier"]

            # EntityA has claims → coverage_pct > 0
            assert regen["coverage_snapshot"].get(f"{_PREFIX}EntityA", 0) > 0
            # EntityB has no claims → coverage_pct = 0
            assert regen["coverage_snapshot"].get(f"{_PREFIX}EntityB", 0) == 0
        finally:
            await pool.close()
    _run(_test())


def test_ds2_clear_entity_absent_from_gaps():
    """DS2: Entity with coverage_state='clear' absent from priority_gaps."""
    _clean()

    async def _do():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}emp")
            sid = await conn.fetchval(
                "INSERT INTO interview_sessions (project_id, employee_id, topic, status, completed_at) "
                "VALUES ($1, $2, $3, 'completed', now()) RETURNING id",
                _PID, uid, f"{_PREFIX}session",
            )
            # Flood EntityC with enough claims to reach 'clear' (coverage >= 50%)
            # EntityC: expected=2, criticality=0.3
            # coverage_pct = (covered_criticality / (expected_count * expected_criticality)) * 100
            # need covered_criticality >= 0.5 * 2 * 0.3 = 0.3
            # each claim with criticality=0.3 gives covered_criticality=0.3 → 1 claim = 50%
            for pred in ("task_1", "task_2", "task_3"):
                await conn.execute(
                    "INSERT INTO claims (user_id, project_id, subject_entity, predicate, object_value, "
                    "evidence_text, source_type, corroboration_level, sensitivity, session_id, "
                    "employee_id, criticality) "
                    "VALUES ($1, $2, $3, $4, 'done', 'documented', 'interview', "
                    "'single_source', 'restricted', $5, $1, 0.3)",
                    uid, _PID, f"{_PREFIX}EntityC", pred, sid,
                )
            return str(sid)
        finally:
            await conn.close()
    sid = _run(_do())

    async def _test():
        pool = await asyncpg.create_pool(_DB_URL, min_size=1, max_size=2)
        try:
            result = await regenerate_dossier(pool, sid)
            assert "error" not in result

            row = await pool.fetchrow(
                "SELECT dossier FROM interview_sessions WHERE id = $1", sid
            )
            dossier = row["dossier"]
            if isinstance(dossier, str):
                dossier = json.loads(dossier)
            regen = dossier["regenerated_dossier"]

            gap_entities = {g["entity"] for g in regen["priority_gaps"]}
            assert f"{_PREFIX}EntityC" not in gap_entities
        finally:
            await pool.close()
    _run(_test())


def test_ds3_open_thread_carried():
    """DS3: open_thread from session carried into dossier."""
    _clean()
    sid, _ = _make_session_with_claims()

    async def _test():
        pool = await asyncpg.create_pool(_DB_URL, min_size=1, max_size=2)
        try:
            result = await regenerate_dossier(pool, sid)
            assert "error" not in result
            assert result["threads_count"] > 0

            row = await pool.fetchrow(
                "SELECT dossier FROM interview_sessions WHERE id = $1", sid
            )
            dossier = row["dossier"]
            if isinstance(dossier, str):
                dossier = json.loads(dossier)
            regen = dossier["regenerated_dossier"]

            thread_subjects = {t["subject"] for t in regen["open_threads"]}
            assert f"{_PREFIX}EntityA" in thread_subjects
        finally:
            await pool.close()
    _run(_test())


def test_ds4_idempotent():
    """DS4: Running dossier_regen twice → same result, no dup cell_run."""
    _clean()
    sid, _ = _make_session_with_claims()

    async def _test():
        pool = await asyncpg.create_pool(_DB_URL, min_size=1, max_size=2)
        try:
            r1 = await regenerate_dossier(pool, sid)
            assert "error" not in r1

            r2 = await regenerate_dossier(pool, sid)
            assert r2.get("error") == "already_completed"

            count = await pool.fetchval(
                "SELECT COUNT(*) FROM cell_runs WHERE cell_type = 'dossier_regen' "
                "AND metrics->>'session_id' = $1 AND status = 'completed'",
                sid,
            )
            assert count == 1
        finally:
            await pool.close()
    _run(_test())


def test_ds5_cold_build_no_prior():
    """DS5: Cold-build session1 (no prior session) → dossier from entity_expected_claims."""
    _clean()

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}emp")
            sid = await conn.fetchval(
                "INSERT INTO interview_sessions (project_id, employee_id, topic, status) "
                "VALUES ($1, $2, $3, 'scheduled') RETURNING id",
                _PID, uid, f"{_PREFIX}session_cold",
            )
            state = InterviewState(str(sid), _PID, uid)
            state = await prepare_dossier(conn, state)

            assert state.state == "open_topic"
            assert len(state.dossier_entities) >= 3
            names = [e["name"] for e in state.dossier_entities]
            assert f"{_PREFIX}EntityA" in names
            assert f"{_PREFIX}EntityB" in names
            assert f"{_PREFIX}EntityC" in names
            # Ordered by criticality DESC
            crits = [e["criticality"] for e in state.dossier_entities]
            assert crits == sorted(crits, reverse=True)
        finally:
            await conn.close()
    _run(_test())


def test_ds5b_warm_build_with_prior():
    """DS5b: prepare_dossier with prior regenerated dossier uses priority_gaps ordering."""
    _clean()
    sid, uid = _make_session_with_claims()

    async def _test():
        pool = await asyncpg.create_pool(_DB_URL, min_size=1, max_size=2)
        try:
            await regenerate_dossier(pool, sid)

            conn = await pool.acquire()
            try:
                sid2 = await conn.fetchval(
                    "INSERT INTO interview_sessions (project_id, employee_id, topic, status) "
                    "VALUES ($1, $2, $3, 'scheduled') RETURNING id",
                    _PID, uid, f"{_PREFIX}session2",
                )
                state = InterviewState(str(sid2), _PID, uid)
                state = await prepare_dossier(conn, state)

                assert state.state == "open_topic"
                assert len(state.dossier_entities) >= 2
                # Warm path orders by priority_gaps (criticality DESC)
                test_ents = [e for e in state.dossier_entities if e["name"].startswith(_PREFIX)]
                crits = [e.get("criticality", 0) for e in test_ents]
                assert crits == sorted(crits, reverse=True)
            finally:
                await pool.release(conn)
        finally:
            await pool.close()
    _run(_test())
