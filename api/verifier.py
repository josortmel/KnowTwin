"""KnowTwin Verifier — batch QA of Curator pre-output.

NEVER writes or modifies claims. Read-only audit → verifier_reports.
Different model from Curator (config validation enforced).
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from db import get_pool
from permissions import check_access
from curator import trust_tier_from_hint, _REQUIRED_PREDICATES

log = logging.getLogger("knowtwin.verifier")

router = APIRouter(prefix="/projects", tags=["verifier"])

_MAX_RERUNS = 1

_VERIFIER_SYSTEM_PROMPT = """You are a knowledge verification engine for employee offboarding QA.
Audit the Curator's output for a project. Check:
1. Missed entities: GLiNER found entities not covered by any claim
2. Trust tier mis-assignments: claims with trust_tier inconsistent with document type
3. Undetected contradictions: claims about same entity+predicate with conflicting values not flagged
4. Structural gaps: expected knowledge areas with no claims

Return JSON: {
  "missed_entities": [{"entity_name": "...", "reason": "..."}],
  "misclassified_tiers": [{"claim_subject": "...", "current_tier": N, "expected_tier": N, "reason": "..."}],
  "undetected_contradictions": [{"subject": "...", "predicate": "...", "values": ["...", "..."], "reason": "..."}],
  "structural_gaps": [{"entity_name": "...", "missing_predicate": "...", "reason": "..."}]
}"""


async def run_verifier(pool: asyncpg.Pool, project_id: int, user_id: int) -> dict:
    """Run verifier QA on a project. Returns summary dict."""
    results = {
        "missed_entities": 0, "misclassified_tiers": 0,
        "undetected_contradictions": 0, "structural_gaps": 0,
        "report_id": None,
    }

    async with pool.acquire() as conn:
        lock_key = int(hashlib.sha256(f"verifier:{project_id}".encode()).hexdigest()[:15], 16)
        acquired = await conn.fetchval("SELECT pg_try_advisory_lock($1)", lock_key)
        if not acquired:
            return {"error": "already_running"}

        try:
            rerun_count = await conn.fetchval(
                "SELECT COUNT(*) FROM verifier_reports WHERE project_id = $1", project_id
            )
            if rerun_count > _MAX_RERUNS:
                return {"error": "max_reruns_exceeded", "count": rerun_count}

            # 1. Find missed entities (GLiNER-discovered but no claims)
            missed = await _find_missed_entities(conn, project_id)
            results["missed_entities"] = len(missed)

            # 2. Check trust_tier assignments
            misclassified = await _check_trust_tiers(conn, project_id)
            results["misclassified_tiers"] = len(misclassified)

            # 3. Independent contradiction detection
            contradictions = await _find_undetected_contradictions(conn, project_id)
            results["undetected_contradictions"] = len(contradictions)

            # 4. Structural completeness (gap check)
            gaps = await _check_structural_gaps(conn, project_id)
            results["structural_gaps"] = len(gaps)

            # 5. Write verifier_report
            report_id = await conn.fetchval("""
                INSERT INTO verifier_reports
                (project_id, run_type, missed_entities, misclassified_tiers,
                 undetected_contradictions, structural_gaps)
                VALUES ($1, 'pre_interview', $2::jsonb, $3::jsonb, $4::jsonb, $5::jsonb)
                RETURNING id
            """,
                project_id,
                json.dumps(missed),
                json.dumps(misclassified),
                json.dumps(contradictions),
                json.dumps(gaps),
            )
            results["report_id"] = str(report_id)

        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", lock_key)

    return results


async def _find_missed_entities(conn, project_id: int) -> list[dict]:
    """Entities in document_entity_links but with no claims."""
    rows = await conn.fetch("""
        SELECT DISTINCT n.name AS entity_name, n.type AS entity_type
        FROM document_entity_links del
        JOIN documents d ON d.id = del.document_id
        JOIN nodes n ON n.id = del.entity_node_id
        LEFT JOIN claims c ON c.subject_entity = n.name AND c.project_id = $1
            AND c.corroboration_level IN ('single_source','corroborated','corroborated_by_employee','validated')
        WHERE d.project_id = $1 AND d.status = 'indexed'
          AND c.id IS NULL
    """, project_id)
    return [{"entity_name": r["entity_name"], "entity_type": r["entity_type"],
             "reason": "GLiNER-discovered entity with no promoted claims"} for r in rows]


async def _check_trust_tiers(conn, project_id: int) -> list[dict]:
    """Claims where trust_tier doesn't match document trust_hint.
    Traces: claim.source_id → document_chunks.id → documents.trust_hint."""
    rows = await conn.fetch("""
        SELECT c.subject_entity, c.trust_tier AS claim_tier, d.trust_hint, d.filename
        FROM claims c
        JOIN document_chunks dc ON dc.id = c.source_id::uuid
        JOIN documents d ON d.id = dc.document_id
        WHERE c.project_id = $1
          AND c.source_id IS NOT NULL
          AND d.trust_hint IS NOT NULL
          AND c.corroboration_level IN ('single_source','corroborated','corroborated_by_employee','validated')
    """, project_id)

    misclassified = []
    for r in rows:
        expected = trust_tier_from_hint(r["trust_hint"])
        if r["claim_tier"] != expected:
            misclassified.append({
                "claim_subject": r["subject_entity"],
                "current_tier": r["claim_tier"],
                "expected_tier": expected,
                "reason": f"Document '{r['filename']}' is {r['trust_hint']} (tier {expected})",
            })
    return misclassified


async def _find_undetected_contradictions(conn, project_id: int) -> list[dict]:
    """Claims with same subject+predicate, different object_value, NOT flagged disputed."""
    rows = await conn.fetch("""
        SELECT a.subject_entity, a.predicate,
               a.object_value AS val_a, b.object_value AS val_b
        FROM claims a
        JOIN claims b ON a.subject_entity = b.subject_entity
                     AND a.predicate = b.predicate
                     AND a.id < b.id
        WHERE a.project_id = $1 AND b.project_id = $1
          AND a.corroboration_level IN ('single_source','corroborated','corroborated_by_employee','validated')
          AND b.corroboration_level IN ('single_source','corroborated','corroborated_by_employee','validated')
          AND a.object_value IS NOT NULL AND b.object_value IS NOT NULL
          AND a.object_value != b.object_value
          AND a.dispute_state = 'undisputed' AND b.dispute_state = 'undisputed'
    """, project_id)

    return [{"subject": r["subject_entity"], "predicate": r["predicate"],
             "values": [r["val_a"], r["val_b"]],
             "reason": "conflicting values not flagged as disputed"} for r in rows]


async def _check_structural_gaps(conn, project_id: int) -> list[dict]:
    """Same gap check as curator, for independent verification."""
    gaps = []
    entities = await conn.fetch("""
        SELECT DISTINCT ec.entity_name, ec.entity_type
        FROM entity_expected_claims ec
        WHERE ec.project_id = $1
    """, project_id)

    for ent in entities:
        required = _REQUIRED_PREDICATES.get(ent["entity_type"], [])
        if not required:
            continue
        existing = await conn.fetch("""
            SELECT DISTINCT predicate FROM claims
            WHERE project_id = $1 AND subject_entity = $2
              AND corroboration_level IN ('single_source','corroborated','corroborated_by_employee','validated')
        """, project_id, ent["entity_name"])
        existing_set = {r["predicate"] for r in existing}
        for pred in required:
            if pred not in existing_set:
                gaps.append({
                    "entity_name": ent["entity_name"],
                    "missing_predicate": pred,
                    "reason": f"expected for {ent['entity_type']}",
                })
    return gaps


@router.post("/{project_id}/verifier/run")
async def trigger_verifier_run(
    project_id: int,
    actor: dict = Depends(get_current_user),
) -> dict:
    """Trigger verifier QA run. Curator/admin only."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await check_access(conn, actor, project_id, "curator")

    result = await run_verifier(pool, project_id, int(actor["sub"]))
    if result.get("error"):
        if result["error"] == "already_running":
            raise HTTPException(409, "verifier run already in progress")
        if result["error"] == "max_reruns_exceeded":
            raise HTTPException(422, f"max re-runs exceeded ({result['count']})")
    return result
