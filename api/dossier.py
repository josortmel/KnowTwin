"""KnowTwin Dossier regeneration -- inter-session metacognition.

Triggered by pg_notify('knowtwin_dossier_regen', session_id) after curator_post.
Recomputes coverage snapshot, prioritized gaps, open threads, and contradictions
so session N+1 opens from session N's learning.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from uuid import UUID as _UUID

import asyncpg

log = logging.getLogger("knowtwin.dossier")


async def regenerate_dossier(pool: asyncpg.Pool, session_id: str) -> dict:
    """Recompute dossier after curator_post. Idempotent per session_id."""
    try:
        _UUID(session_id)
    except (ValueError, TypeError):
        return {"error": "invalid_session_id"}

    async with pool.acquire() as conn:
        lock_key = int(hashlib.sha256(
            f"dossier_regen:{session_id}".encode()
        ).hexdigest()[:15], 16)

        async with conn.transaction():
            acquired = await conn.fetchval("SELECT pg_try_advisory_xact_lock($1)", lock_key)
            if not acquired:
                return {"error": "already_running"}

            already = await conn.fetchval(
                "SELECT 1 FROM cell_runs WHERE cell_type = 'dossier_regen' "
                "AND metrics->>'session_id' = $1 AND status = 'completed'",
                session_id,
            )
            if already:
                return {"error": "already_completed", "session_id": session_id}

            session = await conn.fetchrow(
                "SELECT id, project_id, employee_id, dossier "
                "FROM interview_sessions WHERE id = $1",
                session_id,
            )
            if session is None:
                return {"error": "session_not_found"}

            pid = session["project_id"]
            eid = session["employee_id"]

            coverage_rows = await conn.fetch(
                "SELECT entity_name, coverage_pct, coverage_state, "
                "expected_criticality FROM entity_coverage WHERE project_id = $1",
                pid,
            )
            coverage_snapshot = {
                r["entity_name"]: float(r["coverage_pct"])
                if r["coverage_pct"] is not None else 0.0
                for r in coverage_rows
            }

            priority_gaps = sorted(
                [
                    {
                        "entity": r["entity_name"],
                        "expected_criticality": float(r["expected_criticality"]),
                        "coverage_pct": float(r["coverage_pct"])
                        if r["coverage_pct"] is not None else 0.0,
                    }
                    for r in coverage_rows
                    if r["coverage_state"] in ("unknown", "partial")
                ],
                key=lambda x: x["expected_criticality"],
                reverse=True,
            )

            open_thread_rows = await conn.fetch("""
                SELECT id, subject_entity, predicate, corroboration_level, dispute_state
                FROM claims
                WHERE session_id = $1
                  AND (corroboration_level = 'single_source' OR dispute_state = 'disputed')
            """, session_id)
            open_threads = [
                {
                    "claim_id": str(r["id"]),
                    "subject": r["subject_entity"],
                    "predicate": r["predicate"],
                    "reason": "disputed" if r["dispute_state"] == "disputed" else "unverified",
                }
                for r in open_thread_rows
            ]

            contradiction_rows = await conn.fetch("""
                SELECT id, disputed_by_claim_id, subject_entity
                FROM claims
                WHERE project_id = $1 AND dispute_state = 'disputed'
            """, pid)
            contradictions = [
                {
                    "claim_id": str(r["id"]),
                    "disputed_by": str(r["disputed_by_claim_id"])
                    if r["disputed_by_claim_id"] else None,
                    "subject": r["subject_entity"],
                }
                for r in contradiction_rows
            ]

            regenerated = {
                "coverage_snapshot": coverage_snapshot,
                "priority_gaps": priority_gaps,
                "open_threads": open_threads,
                "contradictions": contradictions,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "prior_session_id": session_id,
            }

            existing_dossier = session["dossier"]
            if isinstance(existing_dossier, str):
                existing_dossier = json.loads(existing_dossier)
            if existing_dossier is None:
                existing_dossier = {}
            existing_dossier["regenerated_dossier"] = regenerated

            await conn.execute(
                "UPDATE interview_sessions SET dossier = $1::jsonb WHERE id = $2",
                json.dumps(existing_dossier), session_id,
            )

            next_session = await conn.fetchval(
                "SELECT id FROM interview_sessions "
                "WHERE project_id = $1 AND employee_id = $2 AND status = 'scheduled' "
                "ORDER BY created_at ASC LIMIT 1",
                pid, eid,
            )
            if next_session:
                next_row = await conn.fetchrow(
                    "SELECT dossier FROM interview_sessions WHERE id = $1", next_session
                )
                next_dossier = next_row["dossier"] if next_row else None
                if isinstance(next_dossier, str):
                    next_dossier = json.loads(next_dossier)
                if next_dossier is None:
                    next_dossier = {}
                next_dossier["regenerated_dossier"] = regenerated
                await conn.execute(
                    "UPDATE interview_sessions SET dossier = $1::jsonb WHERE id = $2",
                    json.dumps(next_dossier), next_session,
                )

            await conn.execute(
                "INSERT INTO cell_runs (cell_type, agent_id, model, metrics, status, finished_at) "
                "VALUES ('dossier_regen', 1, 'n/a', $1::jsonb, 'completed', now())",
                json.dumps({
                    "session_id": session_id,
                    "gaps_count": len(priority_gaps),
                    "threads_count": len(open_threads),
                    "contradictions_count": len(contradictions),
                }),
            )

    return {
        "gaps_count": len(priority_gaps),
        "threads_count": len(open_threads),
        "contradictions_count": len(contradictions),
        "coverage_entities": len(coverage_snapshot),
    }
