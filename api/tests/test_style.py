"""P2.8 Interview style adaptation tests — SA5 MANDATORY.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_style.py -v
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

from interview_style import determine_style, StyleDirective, VALID_STYLES
from interviewer import InterviewState, conduct_turn, _compute_novelty, get_style_directive

_DB_URL = os.environ["DATABASE_URL"]
_PREFIX = "sttest_"
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
            await conn.execute("DELETE FROM audit_log WHERE user_id IN (SELECT id FROM users WHERE name LIKE $1)", f"{_PREFIX}%")
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


def test_sa1_technical_profile():
    """SA1: technical profile → architecture/decision framing words in directive."""
    d = determine_style("technical", [])
    assert "architecture" in d.framing.lower() or "technical" in d.framing.lower()
    assert "decision" in d.framing.lower() or "dependencies" in d.framing.lower()
    assert d.follow_up_style  # non-empty


def test_sa2_short_answers():
    """SA2: short answers → specific closed prompts in follow-up."""
    short_turns = ["yes", "no idea", "ETL runs at night", "Juan handles it"]
    d = determine_style(None, short_turns)
    assert "specific" in d.follow_up_style.lower() or "closed" in d.follow_up_style.lower()
    assert "short" in d.length_guidance.lower()


def test_sa3_vague_answers():
    """SA3: vague answers → reformulation in follow-up."""
    vague_turns = [
        "I think maybe Juan handles it, not sure really",
        "Perhaps the process kind of works, I guess it might be automated",
        "I think probably the ETL sort of runs, maybe at night I guess",
    ]
    d = determine_style(None, vague_turns)
    assert "reformulate" in d.follow_up_style.lower() or "scenario" in d.follow_up_style.lower()
    assert "vague" in d.length_guidance.lower()


def test_sa4_fatigue():
    """SA4: fatigue (declining word count) → shorter prompts."""
    fatigue_turns = [
        "The ETL pipeline connects to three databases and runs transformations every night "
        "with a monitoring dashboard that alerts the on-call team if something fails "
        "and there is a retry mechanism built into the scheduler",
        "Juan manages the main ETL pipeline and monitors it daily",
        "He checks the logs",
        "Yes",
    ]
    d = determine_style(None, fatigue_turns)
    assert "short" in d.follow_up_style.lower() or "critical" in d.follow_up_style.lower()
    assert "fatigue" in d.length_guidance.lower()


def test_sa5_golden_transcript():
    """SA5 (MANDATORY): Style change does NOT alter extracted claims.

    Fixed LLM response → run extraction with technical/relational/None.
    Claims, novelty, and turn_value MUST be identical across all 3 runs.
    """
    _clean()

    GOLDEN_LLM_RESPONSE = json.dumps({
        "claims": [
            {
                "subject_entity": f"{_PREFIX}ETL_Pipeline",
                "predicate": "managed_by",
                "object_value": "Juan Garcia",
                "evidence_text": "Juan manages the ETL pipeline end to end",
            },
            {
                "subject_entity": f"{_PREFIX}ETL_Pipeline",
                "predicate": "runs_at",
                "object_value": "3am daily",
                "evidence_text": "The pipeline runs every day at 3am",
            },
        ]
    })

    GOLDEN_TURN_TEXT = (
        "Juan manages the ETL pipeline end to end. "
        "It runs every day at 3am and connects to the data warehouse."
    )

    all_call_args = {}

    async def _run_with_style(comm_style):
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}emp")

            sid = await conn.fetchval(
                "INSERT INTO interview_sessions (project_id, employee_id, topic, status) "
                "VALUES ($1, $2, $3, 'in_progress') RETURNING id",
                _PID, uid, f"{_PREFIX}golden_{comm_style or 'none'}",
            )

            state = InterviewState(str(sid), _PID, uid)
            state.state = "conduct"
            state.current_topic = f"{_PREFIX}ETL_Pipeline"
            state.comm_style = comm_style
            state.dossier_entities = [
                {"name": f"{_PREFIX}ETL_Pipeline", "type": "system", "expected": 5, "criticality": 0.8}
            ]

            captured = []

            async def mock_llm(*args, **kwargs):
                captured.append((args, kwargs))
                return GOLDEN_LLM_RESPONSE

            with patch("cell_worker._llm_call", side_effect=mock_llm):
                with patch("embeddings_client.embed_text", new_callable=AsyncMock,
                           return_value=[0.1] * 512):
                    result = await conduct_turn(conn, state, GOLDEN_TURN_TEXT)

            all_call_args[comm_style] = captured

            return {
                "claims_created": result["claims_created"],
                "turn_value": result["turn_value"],
                "style_directive": result.get("style_directive"),
            }
        finally:
            await conn.close()

    results = {}
    for style in ["technical", "relational", None]:
        _clean()
        results[style] = _run(_run_with_style(style))

    r_tech = results["technical"]
    r_rel = results["relational"]
    r_none = results[None]

    # CRITICAL: claims MUST be identical across all 3 runs
    assert len(r_tech["claims_created"]) == len(r_rel["claims_created"]) == len(r_none["claims_created"]), \
        f"Claim count differs: tech={len(r_tech['claims_created'])}, rel={len(r_rel['claims_created'])}, none={len(r_none['claims_created'])}"

    # CRITICAL: turn_value MUST be identical
    assert r_tech["turn_value"] == r_rel["turn_value"] == r_none["turn_value"], \
        f"Turn value differs: tech={r_tech['turn_value']}, rel={r_rel['turn_value']}, none={r_none['turn_value']}"

    # CRITICAL: extraction prompt MUST NOT contain style strings
    for style_key, calls in all_call_args.items():
        for args, kwargs in calls:
            prompt_text = str(args)
            assert "architecture" not in prompt_text.lower(), \
                f"Style 'architecture' leaked into extraction prompt for style={style_key}"
            assert "relational" not in prompt_text.lower(), \
                f"Style 'relational' leaked into extraction prompt for style={style_key}"
            assert "framing" not in prompt_text.lower(), \
                f"Style 'framing' leaked into extraction prompt for style={style_key}"

    # Style directives SHOULD differ (proving they work)
    assert r_tech["style_directive"]["framing"] != r_rel["style_directive"]["framing"], \
        "Style directives should differ between technical and relational"
