"""KnowTwin Interviewer — 5-state interview pipeline.

States: prepare_dossier → open_topic → conduct → close_topic → write_rollup.
Each turn: extract claims → create(single_source) → promote(embed) → immediately.
Convergence: turn_value < 0.15 for N=2 consecutive AND no critical entity 'unknown'.
Checkpointed via interview_sessions.dossier (Postgres).
"""
from __future__ import annotations

import json
import logging
import secrets
from typing import Optional
from uuid import UUID

import asyncpg

log = logging.getLogger("knowtwin.interviewer")

CONVERGENCE_THRESHOLD = 0.15
CONVERGENCE_N = 2
CRITICAL_ENTITY_THRESHOLD = 0.7


class InterviewState:
    """Mutable interview state, persisted to interview_sessions.dossier."""

    def __init__(self, session_id: str, project_id: int, employee_id: int,
                 state: str = "prepare_dossier", data: dict = None):
        self.session_id = session_id
        self.project_id = project_id
        self.employee_id = employee_id
        self.state = state
        self.turn_count = 0
        self.turn_values: list[float] = []
        self.topics_covered: list[str] = []
        self.current_topic: Optional[str] = None
        self.claims_this_session: list[str] = []
        self.entities_seen: set[str] = set()
        self.dossier_entities: list[dict] = []
        if data:
            self._load(data)

    def _load(self, data: dict):
        self.state = data.get("state", self.state)
        self.turn_count = data.get("turn_count", 0)
        self.turn_values = data.get("turn_values", [])
        self.topics_covered = data.get("topics_covered", [])
        self.current_topic = data.get("current_topic")
        self.claims_this_session = data.get("claims_this_session", [])
        self.entities_seen = set(data.get("entities_seen", []))
        self.dossier_entities = data.get("dossier_entities", [])

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "turn_count": self.turn_count,
            "turn_values": self.turn_values,
            "topics_covered": self.topics_covered,
            "current_topic": self.current_topic,
            "claims_this_session": self.claims_this_session,
            "entities_seen": list(self.entities_seen),
            "dossier_entities": self.dossier_entities,
        }


async def load_state(conn, session_id: str) -> Optional[InterviewState]:
    """Load interview state from DB."""
    row = await conn.fetchrow(
        "SELECT id, project_id, employee_id, dossier, status FROM interview_sessions WHERE id = $1",
        session_id,
    )
    if row is None:
        return None
    data = row["dossier"]
    if isinstance(data, str):
        data = json.loads(data)
    return InterviewState(
        session_id=str(row["id"]),
        project_id=row["project_id"],
        employee_id=row["employee_id"],
        data=data or {},
    )


async def save_state(conn, state: InterviewState):
    """Persist interview state to DB."""
    await conn.execute(
        "UPDATE interview_sessions SET dossier = $1::jsonb WHERE id = $2",
        json.dumps(state.to_dict()), state.session_id,
    )


async def prepare_dossier(conn, state: InterviewState) -> InterviewState:
    """Load entities + coverage gaps for the project → build interview dossier."""
    entities = await conn.fetch("""
        SELECT entity_name, entity_type, expected_count, expected_criticality
        FROM entity_expected_claims
        WHERE project_id = $1
        ORDER BY expected_criticality DESC
    """, state.project_id)

    state.dossier_entities = [
        {"name": r["entity_name"], "type": r["entity_type"],
         "expected": r["expected_count"], "criticality": float(r["expected_criticality"])}
        for r in entities
    ]
    state.state = "open_topic"
    return state


async def open_topic(conn, state: InterviewState) -> InterviewState:
    """Select next topic (entity with highest uncovered criticality)."""
    covered_entities = set(state.topics_covered)
    for ent in state.dossier_entities:
        if ent["name"] not in covered_entities:
            state.current_topic = ent["name"]
            state.state = "conduct"
            return state
    state.state = "write_rollup"
    return state


async def conduct_turn(conn, state: InterviewState, user_text: str) -> dict:
    """Process one interview turn. Returns turn result."""
    state.turn_count += 1

    claims_created = []
    turn_value = 0.0

    delimiter = f"__KT_{secrets.token_hex(8)}__"
    safe_text = f"{delimiter}\n{user_text[:3000]}\n{delimiter}"

    try:
        from cell_worker import _llm_call
        raw = await _llm_call(
            "Extract factual claims from the employee's response. "
            "Return JSON: {\"claims\": [{\"subject_entity\": \"...\", \"predicate\": \"...\", "
            "\"object_value\": \"...\", \"evidence_text\": \"...\"}]}",
            f"Topic: {state.current_topic}\nEmployee response:\n{safe_text}",
        )
        data = json.loads(raw)
        raw_claims = data.get("claims", [])
    except Exception as exc:
        log.warning("LLM extraction failed turn %d: %r", state.turn_count, exc)
        raw_claims = []

    for cd in raw_claims:
        if not cd.get("subject_entity") or not cd.get("evidence_text"):
            continue

        subject = cd["subject_entity"][:500]
        state.entities_seen.add(subject)

        novelty = await _compute_novelty(conn, state.project_id, subject,
                                          cd.get("predicate", ""), cd.get("object_value", ""))
        criticality = await _get_entity_criticality(conn, state.project_id, subject)

        try:
            claim_id = await conn.fetchval(
                """
                INSERT INTO claims
                (user_id, project_id, subject_entity, predicate, object_value,
                 evidence_text, source_type, employee_id, session_id, sensitivity,
                 corroboration_level, criticality, novelty)
                VALUES ($1, $2, $3, $4, $5, $6, 'interview', $7, $8, 'restricted',
                        'single_source', $9, $10)
                RETURNING id
                """,
                state.employee_id, state.project_id,
                subject, cd.get("predicate", "relates_to")[:200],
                cd.get("object_value"), cd["evidence_text"][:2000],
                state.employee_id, state.session_id,
                criticality, novelty,
            )
            claims_created.append(str(claim_id))
            state.claims_this_session.append(str(claim_id))

            # Promote + embed immediately
            try:
                from embeddings_client import embed_text
                vec = await embed_text(cd["evidence_text"][:2000], "passage")
                if vec is not None:
                    await conn.execute(
                        "UPDATE claims SET embedding = $1::vector WHERE id = $2",
                        str(vec), claim_id,
                    )
            except Exception:
                pass

            claim_value = criticality * novelty
            if novelty >= 0.5:
                turn_value += claim_value

        except Exception as exc:
            log.warning("Claim insert failed: %r", exc)

    state.turn_values.append(turn_value)

    converged = _check_convergence(state)

    if converged:
        state.topics_covered.append(state.current_topic)
        state.current_topic = None
        state.state = "close_topic"

    await save_state(conn, state)

    return {
        "turn": state.turn_count,
        "claims_created": claims_created,
        "turn_value": round(turn_value, 3),
        "converged": converged,
        "state": state.state,
        "topic": state.current_topic,
    }


async def close_topic(conn, state: InterviewState) -> InterviewState:
    """Close current topic, move to next or write_rollup."""
    has_critical_unknown = await _has_critical_unknown_entity(conn, state)
    if has_critical_unknown:
        state.state = "open_topic"
    else:
        remaining = [e for e in state.dossier_entities
                     if e["name"] not in set(state.topics_covered)]
        if remaining:
            state.state = "open_topic"
        else:
            state.state = "write_rollup"
    return state


async def write_rollup(conn, state: InterviewState) -> str:
    """Write session rollup + emit curator_post notification."""
    claims = await conn.fetch("""
        SELECT subject_entity, predicate, object_value, evidence_text
        FROM claims WHERE session_id = $1
        ORDER BY created_at
    """, state.session_id)

    lines = [f"# Interview Rollup — Session {state.session_id}",
             f"Turns: {state.turn_count}, Claims: {len(claims)}",
             f"Topics covered: {', '.join(state.topics_covered)}", ""]

    for c in claims:
        lines.append(f"- {c['subject_entity']}.{c['predicate']}: "
                      f"{c['object_value'] or c['evidence_text'][:80]}")

    rollup = "\n".join(lines)

    await conn.execute("""
        UPDATE interview_sessions
        SET rollup = $1, status = 'completed', completed_at = now(),
            claims_extracted = $2
        WHERE id = $3
    """, rollup, len(claims), state.session_id)

    await conn.execute(
        "SELECT pg_notify('knowtwin_curator_post', $1)", state.session_id
    )

    state.state = "completed"
    await save_state(conn, state)

    return rollup


async def _compute_novelty(conn, project_id: int, subject: str,
                            predicate: str, value: str) -> float:
    """Novelty scoring: new=1.0, confirms=0.1, contradicts=0.8."""
    existing = await conn.fetch("""
        SELECT object_value FROM claims
        WHERE project_id = $1 AND subject_entity = $2 AND predicate = $3
          AND corroboration_level IN ('single_source','corroborated','corroborated_by_employee','validated')
    """, project_id, subject, predicate)

    if not existing:
        return 1.0

    for row in existing:
        if row["object_value"] and value and row["object_value"] != value:
            return 0.8
    return 0.1


async def _get_entity_criticality(conn, project_id: int, entity_name: str) -> float:
    """Get criticality from entity_expected_claims (NOT claims.criticality)."""
    val = await conn.fetchval(
        "SELECT expected_criticality FROM entity_expected_claims "
        "WHERE project_id = $1 AND entity_name = $2",
        project_id, entity_name,
    )
    return float(val) if val is not None else 0.5


def _check_convergence(state: InterviewState) -> bool:
    """turn_value < THRESHOLD for N consecutive turns."""
    if len(state.turn_values) < CONVERGENCE_N:
        return False
    recent = state.turn_values[-CONVERGENCE_N:]
    return all(v < CONVERGENCE_THRESHOLD for v in recent)


async def _has_critical_unknown_entity(conn, state: InterviewState) -> bool:
    """Any entity with criticality >= 0.7 and coverage_state = 'unknown'?"""
    rows = await conn.fetch("""
        SELECT entity_name FROM entity_coverage
        WHERE project_id = $1 AND coverage_state = 'unknown'
          AND expected_criticality >= $2
    """, state.project_id, CRITICAL_ENTITY_THRESHOLD)
    uncovered_critical = {r["entity_name"] for r in rows}
    covered = set(state.topics_covered)
    return bool(uncovered_critical - covered)
