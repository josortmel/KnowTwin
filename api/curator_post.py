"""KnowTwin Curator post-session — event-triggered after each interview.

Triggered by pg_notify('knowtwin_curator_post', session_id).
Reviews tacit (interview) vs documentary claims. doc_strength scoring,
auto-resolution for weak docs, corroboration promotion, sanitization gate.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Optional

import asyncpg

log = logging.getLogger("knowtwin.curator_post")

DOC_STRENGTH_THRESHOLD = 1.5

_JUDGMENT_PATTERNS = re.compile(
    r'\b(incompetent|lazy|stupid|useless|terrible|awful|horrible|idiot|fool|moron)\b',
    re.IGNORECASE,
)


def compute_doc_strength(source_count: int, freshness_score: float, trust_tier: int) -> float:
    """doc_strength = source_count × freshness_score × (trust_tier + 1)."""
    return source_count * freshness_score * (trust_tier + 1)


def sanitize_evidence(text: str) -> tuple[str, bool]:
    """Remove judgment words, keep facts+names. Returns (sanitized, was_modified)."""
    cleaned = _JUDGMENT_PATTERNS.sub("[REDACTED]", text)
    return cleaned, cleaned != text


async def run_curator_post(pool: asyncpg.Pool, session_id: str) -> dict:
    """Post-session curator pass. Idempotent per session_id."""
    results = {
        "auto_resolved": 0, "disputed": 0,
        "promoted": 0, "sanitized": 0,
    }

    async with pool.acquire() as conn:
        lock_key = int(hashlib.sha256(f"curator_post:{session_id}".encode()).hexdigest()[:15], 16)
        acquired = await conn.fetchval("SELECT pg_try_advisory_lock($1)", lock_key)
        if not acquired:
            return {"error": "already_running"}

        try:
            session = await conn.fetchrow(
                "SELECT id, project_id, employee_id FROM interview_sessions WHERE id = $1",
                session_id,
            )
            if session is None:
                return {"error": "session_not_found"}

            pid = session["project_id"]

            already = await conn.fetchval(
                "SELECT 1 FROM cell_runs WHERE cell_type = 'curator_post' "
                "AND metrics->>'session_id' = $1 AND status = 'completed'",
                session_id,
            )
            if already:
                return {"error": "already_completed", "session_id": session_id}

            tacit_claims = await conn.fetch("""
                SELECT id, subject_entity, predicate, object_value, evidence_text,
                       corroboration_level, dispute_state, sensitivity
                FROM claims
                WHERE session_id = $1 AND source_type = 'interview'
                  AND corroboration_level IN ('single_source','corroborated_by_employee')
            """, session_id)

            for tc in tacit_claims:
                sanitized_text, was_modified = sanitize_evidence(tc["evidence_text"])
                if was_modified:
                    await conn.execute(
                        "UPDATE claims SET evidence_text = $1, sensitivity = 'restricted' WHERE id = $2",
                        sanitized_text, tc["id"],
                    )
                    await conn.execute(
                        "INSERT INTO audit_log (user_id, action, resource, resource_id, details) "
                        "VALUES (NULL, 'sanitize_claim', 'claim', $1, $2::jsonb)",
                        str(tc["id"]), json.dumps({"reason": "judgment_removed"}),
                    )
                    results["sanitized"] += 1

                doc_claims = await conn.fetch("""
                    SELECT id, object_value, trust_tier, corroboration_level,
                           dispute_state, doc_strength, source_id
                    FROM claims
                    WHERE project_id = $1 AND subject_entity = $2 AND predicate = $3
                      AND source_type = 'document'
                      AND corroboration_level IN ('single_source','corroborated','corroborated_by_employee','validated')
                """, pid, tc["subject_entity"], tc["predicate"])

                if not doc_claims:
                    continue

                for dc in doc_claims:
                    if dc["object_value"] and tc["object_value"] and dc["object_value"] != tc["object_value"]:
                        source_count = await conn.fetchval(
                            "SELECT GREATEST(COUNT(DISTINCT source_id), 1) FROM claims "
                            "WHERE project_id = $1 AND subject_entity = $2 AND predicate = $3 "
                            "AND object_value = $4 AND source_type = 'document'",
                            pid, tc["subject_entity"], tc["predicate"], dc["object_value"],
                        )
                        freshness = 1.0
                        strength = compute_doc_strength(source_count, freshness, dc["trust_tier"] or 0)

                        if strength < DOC_STRENGTH_THRESHOLD:
                            await conn.execute(
                                "UPDATE claims SET dispute_state = 'resolved_in_favor', "
                                "resolved_by_user_id = NULL, "
                                "resolution_note = $1 WHERE id = $2",
                                f"auto: doc_strength={strength:.2f} below threshold {DOC_STRENGTH_THRESHOLD}",
                                dc["id"],
                            )
                            await conn.execute(
                                "INSERT INTO audit_log (user_id, action, resource, resource_id, details) "
                                "VALUES (NULL, 'auto_resolve', 'claim', $1, $2::jsonb)",
                                str(dc["id"]),
                                json.dumps({"doc_strength": strength, "in_favor_of": str(tc["id"])}),
                            )
                            results["auto_resolved"] += 1
                        else:
                            if dc["dispute_state"] == "undisputed":
                                await conn.execute(
                                    "UPDATE claims SET dispute_state = 'disputed', "
                                    "disputed_by_claim_id = $1, doc_strength = $2 WHERE id = $3",
                                    tc["id"], strength, dc["id"],
                                )
                                await conn.execute(
                                    "UPDATE claims SET dispute_state = 'disputed', "
                                    "disputed_by_claim_id = $1 WHERE id = $2",
                                    dc["id"], tc["id"],
                                )
                                await conn.execute(
                                    "INSERT INTO audit_log (user_id, action, resource, resource_id, details) "
                                    "VALUES (NULL, 'dispute_claim', 'claim', $1, $2::jsonb)",
                                    str(dc["id"]),
                                    json.dumps({"tacit_claim_id": str(tc["id"]), "doc_strength": float(strength)}),
                                )
                                results["disputed"] += 1
                    else:
                        if dc["corroboration_level"] == "single_source":
                            new_level = "corroborated_by_employee"
                            await conn.execute(
                                "UPDATE claims SET corroboration_level = $1, updated_at = now() WHERE id = $2",
                                new_level, dc["id"],
                            )
                            await conn.execute(
                                "INSERT INTO audit_log (user_id, action, resource, resource_id, details) "
                                "VALUES (NULL, 'promote_claim', 'claim', $1, $2::jsonb)",
                                str(dc["id"]),
                                json.dumps({"old_level": "single_source", "new_level": new_level,
                                            "reason": "tacit_corroboration", "tacit_claim_id": str(tc["id"])}),
                            )
                            results["promoted"] += 1

            await conn.execute(
                "INSERT INTO cell_runs (cell_type, agent_id, model, metrics, status, finished_at) "
                "VALUES ('curator_post', 1, 'n/a', $1::jsonb, 'completed', now())",
                json.dumps({"session_id": session_id, **results}),
            )

        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", lock_key)

    return results
