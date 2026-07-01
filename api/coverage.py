"""KnowTwin coverage model — entity_coverage view query + API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_user
from db import get_pool
from permissions import check_access

router = APIRouter(tags=["coverage"])


@router.get("/twin/coverage")
async def get_coverage(
    project_id: int = Query(..., gt=0),
    actor: dict = Depends(get_current_user),
) -> dict:
    """Coverage summary for a project. Consumer/curator/admin."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await check_access(conn, actor, project_id, "consumer")

        rows = await conn.fetch(
            """
            SELECT entity_name, entity_type,
                   confirmed_count, expected_count,
                   covered_criticality, expected_criticality,
                   coverage_pct, coverage_state
            FROM entity_coverage
            WHERE project_id = $1
            ORDER BY coverage_pct ASC, entity_name
            """,
            project_id,
        )

        entities = []
        total_covered = 0.0
        total_expected = 0.0
        for r in rows:
            entities.append({
                "entity_name": r["entity_name"],
                "entity_type": r["entity_type"],
                "confirmed_count": r["confirmed_count"],
                "expected_count": r["expected_count"],
                "covered_criticality": float(r["covered_criticality"]),
                "expected_criticality": float(r["expected_criticality"]),
                "coverage_pct": float(r["coverage_pct"]),
                "coverage_state": r["coverage_state"],
            })
            total_covered += float(r["covered_criticality"])
            total_expected += float(r["expected_count"]) * float(r["expected_criticality"])

        overall_pct = round(total_covered / total_expected * 100, 1) if total_expected > 0 else 0.0

        return {
            "project_id": project_id,
            "overall_coverage_pct": overall_pct,
            "entity_count": len(entities),
            "entities": entities,
        }


@router.get("/graph/entities")
async def get_entities_with_coverage(
    project_id: int = Query(..., gt=0),
    coverage_state: str | None = Query(None),
    actor: dict = Depends(get_current_user),
) -> dict:
    """Entities with coverage state. Consumer/curator/admin."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await check_access(conn, actor, project_id, "consumer")

        query = """
            SELECT entity_name, entity_type, coverage_pct, coverage_state
            FROM entity_coverage
            WHERE project_id = $1
        """
        params: list = [project_id]

        if coverage_state is not None:
            query += " AND coverage_state = $2"
            params.append(coverage_state)

        query += " ORDER BY entity_name"

        rows = await conn.fetch(query, *params)

        return {
            "project_id": project_id,
            "entities": [
                {
                    "entity_name": r["entity_name"],
                    "entity_type": r["entity_type"],
                    "coverage_pct": float(r["coverage_pct"]),
                    "coverage_state": r["coverage_state"],
                }
                for r in rows
            ],
        }
