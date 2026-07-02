"""KnowTwin Disputes — resolution workflow + doc_strength transparency.

Endpoints: list disputes, dispute detail, resolve, assign resolver.
Authz: curator/admin/assigned-resolver only for mutations; deny-by-default.
"""
from __future__ import annotations

import json
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import get_current_user
from db import get_pool
from permissions import check_access

log = logging.getLogger("knowtwin.disputes")

router = APIRouter(prefix="/claims", tags=["disputes"])


class DocStrengthBreakdown(BaseModel):
    source_count: int
    freshness_score: float
    trust_tier: int
    computed_strength: float


class DisputeClaimView(BaseModel):
    claim_id: str
    subject_entity: str
    predicate: str
    object_value: Optional[str] = None
    evidence_text: str
    source_type: str
    sensitivity: str
    corroboration_level: str
    dispute_state: str
    criticality: float
    doc_strength: Optional[float] = None
    doc_strength_breakdown: Optional[DocStrengthBreakdown] = None
    resolution_note: Optional[str] = None
    resolved_by_user_id: Optional[int] = None
    resolver_user_id: Optional[int] = None


class DisputeDetailResponse(BaseModel):
    claim: DisputeClaimView
    counterpart: Optional[DisputeClaimView] = None
    why_resolved: Optional[str] = None


class DisputeListItem(BaseModel):
    claim: DisputeClaimView
    counterpart: Optional[DisputeClaimView] = None


class DisputeListResponse(BaseModel):
    disputes: list[DisputeListItem]
    total: int


class ResolveBody(BaseModel):
    resolution: str = Field(..., pattern="^(in_favor|against)$")
    resolution_note: str = Field(..., min_length=1, max_length=2000)


class AssignResolverBody(BaseModel):
    resolver_user_id: int


async def _compute_breakdown(conn, claim_row: dict) -> Optional[DocStrengthBreakdown]:
    """Compute doc_strength breakdown for a document-type claim."""
    if claim_row.get("source_type") != "document":
        return None
    source_count = await conn.fetchval(
        "SELECT GREATEST(COUNT(DISTINCT source_id), 1)::int FROM claims "
        "WHERE project_id = $1 AND subject_entity = $2 AND predicate = $3 "
        "AND object_value = $4 AND source_type = 'document'",
        claim_row["project_id"], claim_row["subject_entity"],
        claim_row["predicate"], claim_row.get("object_value"),
    )
    freshness_score = 1.0
    trust_tier = claim_row.get("trust_tier") or 0
    return DocStrengthBreakdown(
        source_count=source_count,
        freshness_score=freshness_score,
        trust_tier=trust_tier,
        computed_strength=source_count * freshness_score * (trust_tier + 1),
    )


async def _claim_to_view(conn, row: dict, role: str = "admin") -> DisputeClaimView:
    from permissions import render_evidence
    breakdown = await _compute_breakdown(conn, row)
    return DisputeClaimView(
        claim_id=str(row["id"]),
        subject_entity=row["subject_entity"],
        predicate=row["predicate"],
        object_value=row.get("object_value"),
        evidence_text=render_evidence(role, row["evidence_text"], row.get("sanitized_text")),
        source_type=row["source_type"],
        sensitivity=row["sensitivity"],
        corroboration_level=row["corroboration_level"],
        dispute_state=row["dispute_state"],
        criticality=row.get("criticality", 0.5),
        doc_strength=float(row["doc_strength"]) if row.get("doc_strength") else None,
        doc_strength_breakdown=breakdown,
        resolution_note=row.get("resolution_note"),
        resolved_by_user_id=row.get("resolved_by_user_id"),
        resolver_user_id=row.get("resolver_user_id"),
    )


def _why_resolved(claim_row: dict) -> Optional[str]:
    """Deterministic 'why resolved' from doc_strength inputs."""
    ds = claim_row.get("dispute_state", "")
    if ds not in ("resolved_in_favor", "resolved_against"):
        return None
    note = claim_row.get("resolution_note") or ""
    rby = claim_row.get("resolved_by_user_id")
    if rby is None and note.startswith("auto:"):
        return f"Auto-resolved: {note}"
    if rby is not None:
        return f"Manually resolved by user {rby}: {note}" if note else f"Manually resolved by user {rby}"
    return note or None


_DISPUTE_COLS = (
    "id, subject_entity, predicate, object_value, evidence_text, sanitized_text, "
    "source_type, sensitivity, corroboration_level, dispute_state, criticality, "
    "doc_strength, resolution_note, resolved_by_user_id, resolver_user_id, "
    "trust_tier, project_id, disputed_by_claim_id"
)


@router.get("/disputes", response_model=DisputeListResponse)
async def list_disputes(
    project_id: int = Query(..., gt=0),
    actor: dict = Depends(get_current_user),
):
    """List disputed claims with both versions + doc_strength breakdown."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        role = await check_access(conn, actor, project_id, "curator")

        rows = await conn.fetch(f"""
            SELECT {_DISPUTE_COLS}
            FROM claims
            WHERE project_id = $1 AND dispute_state = 'disputed'
            ORDER BY doc_strength DESC NULLS LAST
        """, project_id)

        items = []
        seen = set()
        for row in rows:
            rid = str(row["id"])
            if rid in seen:
                continue
            seen.add(rid)

            claim_view = await _claim_to_view(conn, dict(row), role)
            counterpart_view = None

            cpart_id = row["disputed_by_claim_id"]
            if cpart_id and str(cpart_id) not in seen:
                seen.add(str(cpart_id))
                cpart = await conn.fetchrow(
                    f"SELECT {_DISPUTE_COLS} FROM claims WHERE id = $1", cpart_id
                )
                if cpart:
                    counterpart_view = await _claim_to_view(conn, dict(cpart), role)

            items.append(DisputeListItem(claim=claim_view, counterpart=counterpart_view))

        return DisputeListResponse(disputes=items, total=len(items))


@router.get("/{claim_id}/dispute-detail", response_model=DisputeDetailResponse)
async def dispute_detail(
    claim_id: UUID,
    actor: dict = Depends(get_current_user),
):
    """Both versions + doc_strength breakdown + resolution status."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_DISPUTE_COLS} FROM claims WHERE id = $1", claim_id
        )
        if row is None:
            raise HTTPException(404, "claim not found")

        role = await check_access(conn, actor, row["project_id"], "consumer")
        if role == "employee":
            raise HTTPException(403, "employees cannot view dispute details")

        claim_view = await _claim_to_view(conn, dict(row), role)

        counterpart_view = None
        cpart_id = row["disputed_by_claim_id"]
        if cpart_id:
            if role in ("admin", "curator"):
                cpart = await conn.fetchrow(
                    f"SELECT {_DISPUTE_COLS} FROM claims WHERE id = $1", cpart_id
                )
            else:
                cpart = await conn.fetchrow(
                    f"SELECT {_DISPUTE_COLS} FROM claims WHERE id = $1 "
                    "AND sensitivity IN ('public', 'team')", cpart_id
                )
            if cpart:
                counterpart_view = await _claim_to_view(conn, dict(cpart), role)

        return DisputeDetailResponse(
            claim=claim_view,
            counterpart=counterpart_view,
            why_resolved=_why_resolved(dict(row)),
        )


@router.put("/{claim_id}/resolve")
async def resolve_dispute(
    claim_id: UUID,
    body: ResolveBody,
    actor: dict = Depends(get_current_user),
):
    """Resolve a disputed claim. Curator/admin/assigned-resolver only."""
    if "\x00" in body.resolution_note:
        raise HTTPException(422, "null bytes not allowed in resolution_note")

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, project_id, dispute_state, resolver_user_id, disputed_by_claim_id "
            "FROM claims WHERE id = $1",
            claim_id,
        )
        if row is None:
            raise HTTPException(404, "claim not found")

        role = await check_access(conn, actor, row["project_id"], "consumer")
        actor_id = int(actor["sub"])

        if not _can_resolve(role, actor_id, row):
            raise HTTPException(403, "only curator, admin, or assigned resolver can resolve disputes")

        if row["dispute_state"] not in ("disputed",):
            raise HTTPException(400, f"claim is not disputed (state: {row['dispute_state']})")

        new_state = f"resolved_{body.resolution}"
        inverse_state = "resolved_against" if body.resolution == "in_favor" else "resolved_in_favor"

        async with conn.transaction():
            await conn.execute(
                "UPDATE claims SET dispute_state = $1, resolution_note = $2, "
                "resolved_by_user_id = $3, updated_at = now() WHERE id = $4",
                new_state, body.resolution_note, actor_id, claim_id,
            )

            await conn.execute(
                "INSERT INTO audit_log (user_id, action, resource, resource_id, details) "
                "VALUES ($1, 'resolve_dispute', 'claim', $2, $3::jsonb)",
                actor_id, str(claim_id),
                json.dumps({
                    "resolution": body.resolution,
                    "note": body.resolution_note,
                    "new_state": new_state,
                }),
            )

            cpart_id = row["disputed_by_claim_id"]
            if cpart_id:
                await conn.execute(
                    "UPDATE claims SET dispute_state = $1, resolution_note = $2, "
                    "resolved_by_user_id = $3, updated_at = now() WHERE id = $4",
                    inverse_state,
                    f"counterpart of {claim_id} resolved {body.resolution}",
                    actor_id, cpart_id,
                )
                await conn.execute(
                    "INSERT INTO audit_log (user_id, action, resource, resource_id, details) "
                    "VALUES ($1, 'resolve_dispute', 'claim', $2, $3::jsonb)",
                    actor_id, str(cpart_id),
                    json.dumps({
                        "resolution": "against" if body.resolution == "in_favor" else "in_favor",
                        "note": f"counterpart of {claim_id}",
                        "new_state": inverse_state,
                    }),
                )

        return {"status": "resolved", "claim_id": str(claim_id), "new_state": new_state}


@router.put("/{claim_id}/assign-resolver")
async def assign_resolver(
    claim_id: UUID,
    body: AssignResolverBody,
    actor: dict = Depends(get_current_user),
):
    """Assign a resolver to a disputed claim. Curator/admin only."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, project_id, dispute_state FROM claims WHERE id = $1",
            claim_id,
        )
        if row is None:
            raise HTTPException(404, "claim not found")

        await check_access(conn, actor, row["project_id"], "curator")

        resolver_exists = await conn.fetchval(
            "SELECT 1 FROM users WHERE id = $1 AND active = true", body.resolver_user_id
        )
        if not resolver_exists:
            raise HTTPException(404, "resolver user not found")

        is_member = await conn.fetchval(
            "SELECT 1 FROM project_members WHERE project_id = $1 AND user_id = $2",
            row["project_id"], body.resolver_user_id,
        )
        if not is_member:
            raise HTTPException(422, "resolver must be a project member")

        await conn.execute(
            "UPDATE claims SET resolver_user_id = $1, updated_at = now() WHERE id = $2",
            body.resolver_user_id, claim_id,
        )

        await conn.execute(
            "INSERT INTO audit_log (user_id, action, resource, resource_id, details) "
            "VALUES ($1, 'assign_resolver', 'claim', $2, $3::jsonb)",
            int(actor["sub"]), str(claim_id),
            json.dumps({"resolver_user_id": body.resolver_user_id}),
        )

        return {"status": "assigned", "claim_id": str(claim_id),
                "resolver_user_id": body.resolver_user_id}


def _can_resolve(role: str, actor_id: int, claim_row) -> bool:
    """Curator/admin/assigned-resolver only. Deny-by-default."""
    if role in ("curator", "admin"):
        return True
    resolver_id = claim_row.get("resolver_user_id")
    if resolver_id is not None and resolver_id == actor_id:
        return True
    return False
