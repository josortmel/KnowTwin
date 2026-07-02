"""KnowTwin Scoring — employee knowledge-contribution score.

Quality not quantity. Anti-gaming. Process-not-person framing.
Score = 100 × (0.40·coverage_contrib + 0.20·contradiction_yield
               + 0.20·quality − 0.20·gaming_penalty)
Computed-on-read, never stored.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user
from db import get_pool
from permissions import check_access

log = logging.getLogger("knowtwin.scoring")

router = APIRouter(prefix="/projects", tags=["scoring"])

W_COVERAGE = 0.40
W_CONTRADICTION = 0.20
W_QUALITY = 0.20
W_GAMING = 0.20
GAMING_THRESHOLD = 0.50


class ScoreComponents(BaseModel):
    coverage_contrib: float
    contradiction_yield: float
    quality: float
    gaming_penalty: float


class ScoreResponse(BaseModel):
    employee_id: int
    score: float
    components: ScoreComponents
    claim_count: int


async def compute_score(conn, project_id: int, employee_id: int) -> ScoreResponse:
    """Compute employee knowledge-contribution score. Read-only."""
    claims = await conn.fetch("""
        SELECT id, criticality, corroboration_level, dispute_state,
               actionability, session_id
        FROM claims
        WHERE project_id = $1 AND employee_id = $2
          AND source_type = 'interview'
          AND corroboration_level IN ('single_source', 'corroborated', 'corroborated_by_employee', 'validated')
    """, project_id, employee_id)

    claim_count = len(claims)
    if claim_count == 0:
        return ScoreResponse(
            employee_id=employee_id, score=0.0,
            components=ScoreComponents(
                coverage_contrib=0.0, contradiction_yield=0.0,
                quality=0.0, gaming_penalty=0.0,
            ),
            claim_count=0,
        )

    # Coverage contribution: sum of criticality × novelty (capped per claim)
    # Novelty approximated: claims that are single_source=high novelty,
    # corroborated variants=lower (they confirmed existing)
    novelty_sum = 0.0
    low_novelty_count = 0
    for c in claims:
        level = c["corroboration_level"]
        if level in ("corroborated", "corroborated_by_employee", "validated"):
            novelty = 0.1
        else:
            novelty = 1.0

        capped = min(c["criticality"] * novelty, 1.0)
        novelty_sum += capped

        if novelty <= 0.1:
            low_novelty_count += 1

    # Denominator from entity_coverage
    coverage_total = await conn.fetchval(
        "SELECT COALESCE(NULLIF(SUM(expected_count * expected_criticality), 0), 1.0) "
        "FROM entity_expected_claims WHERE project_id = $1",
        project_id,
    )
    coverage_contrib = min(novelty_sum / float(coverage_total), 1.0)

    # Contradiction yield: claims involved in disputes / total
    dispute_count = sum(
        1 for c in claims
        if c["dispute_state"] in ("disputed", "resolved_in_favor")
    )
    contradiction_yield = dispute_count / claim_count if claim_count > 0 else 0.0

    # Quality: proportion with actionability > 0.5
    actionable = sum(
        1 for c in claims
        if c["actionability"] is not None and c["actionability"] > 0.5
    )
    quality = actionable / claim_count if claim_count > 0 else 0.0

    # Gaming penalty: activates above GAMING_THRESHOLD low-novelty share
    low_novelty_share = low_novelty_count / claim_count if claim_count > 0 else 0.0
    gaming_penalty = max(0.0, (low_novelty_share - GAMING_THRESHOLD) / (1.0 - GAMING_THRESHOLD))

    score = 100.0 * (
        W_COVERAGE * coverage_contrib
        + W_CONTRADICTION * contradiction_yield
        + W_QUALITY * quality
        - W_GAMING * gaming_penalty
    )
    score = max(0.0, round(score, 2))

    return ScoreResponse(
        employee_id=employee_id,
        score=score,
        components=ScoreComponents(
            coverage_contrib=round(coverage_contrib, 4),
            contradiction_yield=round(contradiction_yield, 4),
            quality=round(quality, 4),
            gaming_penalty=round(gaming_penalty, 4),
        ),
        claim_count=claim_count,
    )


@router.get("/{project_id}/employees/{employee_id}/score", response_model=ScoreResponse)
async def get_employee_score(
    project_id: int,
    employee_id: int,
    actor: dict = Depends(get_current_user),
):
    """Employee sees own score, curator/admin sees any."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        role = await check_access(conn, actor, project_id, "employee")
        actor_id = int(actor["sub"])

        if role == "employee" and actor_id != employee_id:
            raise HTTPException(403, "employees can only view own score")

        return await compute_score(conn, project_id, employee_id)


@router.get("/{project_id}/scores")
async def get_all_scores(
    project_id: int,
    actor: dict = Depends(get_current_user),
):
    """All employee scores. Curator/admin only."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await check_access(conn, actor, project_id, "curator")

        employees = await conn.fetch(
            "SELECT DISTINCT user_id FROM project_members "
            "WHERE project_id = $1 AND role = 'employee'",
            project_id,
        )

        scores = []
        for emp in employees:
            s = await compute_score(conn, project_id, emp["user_id"])
            scores.append(s)

    return scores
