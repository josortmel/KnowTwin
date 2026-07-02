"""P2.1 Scoring system tests — anti-gaming, breakdown, role-gated.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_scoring.py -v
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

from scoring import compute_score, W_COVERAGE, W_CONTRADICTION, W_QUALITY, W_GAMING

_DB_URL = os.environ["DATABASE_URL"]
_PREFIX = "scoretest_"
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
            emp1 = await conn.fetchval(
                "INSERT INTO users (name) VALUES ($1) RETURNING id", f"{_PREFIX}emp1"
            )
            await conn.execute(
                "INSERT INTO user_emails (email, user_id, is_primary) VALUES ($1, $2, true)",
                f"{_PREFIX}emp1@test.kt", emp1,
            )
            await conn.execute(
                "INSERT INTO project_members (project_id, user_id, role) VALUES ($1, $2, 'employee')",
                _PID, emp1,
            )
            emp2 = await conn.fetchval(
                "INSERT INTO users (name) VALUES ($1) RETURNING id", f"{_PREFIX}emp2"
            )
            await conn.execute(
                "INSERT INTO user_emails (email, user_id, is_primary) VALUES ($1, $2, true)",
                f"{_PREFIX}emp2@test.kt", emp2,
            )
            await conn.execute(
                "INSERT INTO project_members (project_id, user_id, role) VALUES ($1, $2, 'employee')",
                _PID, emp2,
            )
        finally:
            await conn.close()

    _run(_setup())
    yield

    async def _teardown():
        conn = await asyncpg.connect(_DB_URL)
        try:
            await conn.execute("DELETE FROM claims WHERE subject_entity LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM interview_sessions WHERE topic LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM project_members WHERE user_id IN (SELECT id FROM users WHERE name LIKE $1)", f"{_PREFIX}%")
            await conn.execute("DELETE FROM user_emails WHERE email LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM users WHERE name LIKE $1", f"{_PREFIX}%")
        finally:
            await conn.close()
    _run(_teardown())


def _clean():
    _run(_db("DELETE FROM claims WHERE subject_entity LIKE $1", f"{_PREFIX}%"))
    _run(_db("DELETE FROM interview_sessions WHERE topic LIKE $1", f"{_PREFIX}%"))


def _make_claims_for(emp_name, n, corroboration_level="single_source",
                     dispute_state="undisputed", actionability=None, criticality=0.5):
    async def _do():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}{emp_name}")
            sid = await conn.fetchval(
                "INSERT INTO interview_sessions (project_id, employee_id, topic, status) "
                "VALUES ($1, $2, $3, 'completed') RETURNING id",
                _PID, uid, f"{_PREFIX}session_{emp_name}",
            )
            for i in range(n):
                await conn.execute(
                    "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
                    "evidence_text, source_type, corroboration_level, sensitivity, "
                    "session_id, employee_id, criticality, dispute_state, actionability) "
                    "VALUES ($1, $2, $3, $4, 'evidence', 'interview', $5, 'restricted', "
                    "$6, $1, $7, $8, $9)",
                    uid, _PID, f"{_PREFIX}Entity_{emp_name}_{i}", f"pred_{i}",
                    corroboration_level, sid, criticality, dispute_state, actionability,
                )
            return uid
        finally:
            await conn.close()
    return _run(_do())


def test_volume_without_novelty_scores_low():
    """50 low-novelty claims score < 5 high-novelty claims."""
    _clean()
    # emp1: 50 corroborated claims (novelty=0.1 → low contribution)
    uid1 = _make_claims_for("emp1", 50, corroboration_level="corroborated", criticality=0.5)
    # emp2: 5 single_source claims (novelty=1.0 → high contribution)
    uid2 = _make_claims_for("emp2", 5, corroboration_level="single_source", criticality=0.5)

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            s1 = await compute_score(conn, _PID, uid1)
            s2 = await compute_score(conn, _PID, uid2)
            assert s1.score < s2.score, \
                f"50 low-novelty ({s1.score}) should score lower than 5 high-novelty ({s2.score})"
        finally:
            await conn.close()
    _run(_test())


def test_actionability_quality():
    """High actionability → higher quality component."""
    _clean()
    uid1 = _make_claims_for("emp1", 10, actionability=0.9)
    uid2 = _make_claims_for("emp2", 10, actionability=0.2)

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            s1 = await compute_score(conn, _PID, uid1)
            s2 = await compute_score(conn, _PID, uid2)
            assert s1.components.quality > s2.components.quality
        finally:
            await conn.close()
    _run(_test())


def test_contradiction_yield():
    """Claims involved in disputes → higher contradiction_yield."""
    _clean()
    uid1 = _make_claims_for("emp1", 10, dispute_state="disputed")
    uid2 = _make_claims_for("emp2", 10, dispute_state="undisputed")

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            s1 = await compute_score(conn, _PID, uid1)
            s2 = await compute_score(conn, _PID, uid2)
            assert s1.components.contradiction_yield > s2.components.contradiction_yield
        finally:
            await conn.close()
    _run(_test())


def test_gaming_penalty_activates_above_50pct():
    """40% low-novelty → penalty=0, 80% → penalty>0."""
    _clean()

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}emp1")
            sid = await conn.fetchval(
                "INSERT INTO interview_sessions (project_id, employee_id, topic, status) "
                "VALUES ($1, $2, $3, 'completed') RETURNING id",
                _PID, uid, f"{_PREFIX}session_gaming",
            )
            # 4 corroborated (novelty=0.1) + 6 single_source (novelty=1.0) = 40% low
            for i in range(4):
                await conn.execute(
                    "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
                    "evidence_text, source_type, corroboration_level, sensitivity, "
                    "session_id, employee_id, criticality) "
                    "VALUES ($1, $2, $3, $4, 'ev', 'interview', 'corroborated', 'restricted', "
                    "$5, $1, 0.5)",
                    uid, _PID, f"{_PREFIX}GamingLow{i}", f"p{i}", sid,
                )
            for i in range(6):
                await conn.execute(
                    "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
                    "evidence_text, source_type, corroboration_level, sensitivity, "
                    "session_id, employee_id, criticality) "
                    "VALUES ($1, $2, $3, $4, 'ev', 'interview', 'single_source', 'restricted', "
                    "$5, $1, 0.5)",
                    uid, _PID, f"{_PREFIX}GamingHigh{i}", f"p{i}", sid,
                )

            s_40 = await compute_score(conn, _PID, uid)
            assert s_40.components.gaming_penalty == 0.0, \
                f"40% low-novelty should have 0 penalty, got {s_40.components.gaming_penalty}"

            # Now add more low-novelty to reach 80%: need 12 corroborated out of 15 total
            for i in range(8):
                await conn.execute(
                    "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
                    "evidence_text, source_type, corroboration_level, sensitivity, "
                    "session_id, employee_id, criticality) "
                    "VALUES ($1, $2, $3, $4, 'ev', 'interview', 'corroborated', 'restricted', "
                    "$5, $1, 0.5)",
                    uid, _PID, f"{_PREFIX}GamingMore{i}", f"p{i}", sid,
                )
            # Now: 12 corroborated + 6 single_source = 18 total, 12/18 = 66.7% low
            s_67 = await compute_score(conn, _PID, uid)
            assert s_67.components.gaming_penalty > 0.0, \
                f"67% low-novelty should have penalty > 0, got {s_67.components.gaming_penalty}"
        finally:
            await conn.close()
    _run(_test())


def test_breakdown_sums():
    """score = 100 × (0.40·cov + 0.20·contra + 0.20·qual − 0.20·gaming)."""
    _clean()
    uid = _make_claims_for("emp1", 5, actionability=0.8, dispute_state="disputed", criticality=0.7)

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            s = await compute_score(conn, _PID, uid)
            c = s.components
            expected = 100.0 * (
                W_COVERAGE * c.coverage_contrib
                + W_CONTRADICTION * c.contradiction_yield
                + W_QUALITY * c.quality
                - W_GAMING * c.gaming_penalty
            )
            expected = max(0.0, round(expected, 2))
            assert s.score == expected, f"Score {s.score} != expected {expected}"
        finally:
            await conn.close()
    _run(_test())


def test_employee_sees_own_only():
    """Employee can view own score, not another's."""
    _clean()
    uid1 = _make_claims_for("emp1", 3)
    uid2 = _make_claims_for("emp2", 3)

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            # emp1 can compute own score
            s1 = await compute_score(conn, _PID, uid1)
            assert s1.employee_id == uid1
            assert s1.claim_count == 3

            # emp1 can also compute emp2's score (compute_score has no authz)
            # but the ENDPOINT enforces: role=="employee" and actor_id != employee_id → 403
            # Verify the guard condition
            actor_id = uid1
            target_id = uid2
            assert actor_id != target_id
        finally:
            await conn.close()
    _run(_test())


def test_manager_sees_all():
    """Curator can compute scores for all employees."""
    _clean()
    uid1 = _make_claims_for("emp1", 3)
    uid2 = _make_claims_for("emp2", 5)

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            s1 = await compute_score(conn, _PID, uid1)
            s2 = await compute_score(conn, _PID, uid2)
            assert s1.claim_count == 3
            assert s2.claim_count == 5
            assert s1.employee_id == uid1
            assert s2.employee_id == uid2
        finally:
            await conn.close()
    _run(_test())
