"""KnowTwin GDPR deletion — erasure workflow + retention expiry.

Employee requests deletion → curator reviews → approved = GDPR erase.
Auto-expiry cron uses the same erasure function.
Erasure is INTENTIONALLY irreversible.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import get_current_user
from db import get_pool
from permissions import check_access

log = logging.getLogger("knowtwin.deletion")

router = APIRouter(tags=["deletion"])

MAX_EXPIRY_BATCH = 100


class DeletionRequestCreate(BaseModel):
    reason: Optional[str] = Field(None, max_length=1000)


class ReviewBody(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject)$")
    note: Optional[str] = Field(None, max_length=1000)


async def gdpr_erase_claim(conn, claim_id, requester_id: int, reason_code: str):
    """GDPR erasure — irreversible. Strips ALL personal data from a claim.

    Erases: evidence, entities, employee identity, session link, resolution data,
    entity/document links, related session rollup+turn_texts.
    Used by both manual deletion (curator-approved) and auto-expiry.
    """
    async with conn.transaction():
        # Read session_id BEFORE erasing (will be NULLed)
        pre_row = await conn.fetchrow(
            "SELECT session_id FROM claims WHERE id = $1", claim_id
        )
        pre_session_id = pre_row["session_id"] if pre_row else None

        # Link table cleanup (survive UPDATE — CASCADE only fires on DELETE)
        await conn.execute("DELETE FROM triples WHERE claim_id = $1", claim_id)
        await conn.execute("DELETE FROM claim_entity_links WHERE claim_id = $1", claim_id)
        await conn.execute("DELETE FROM claim_document_links WHERE claim_id = $1", claim_id)

        # Full PII erasure
        await conn.execute("""
            UPDATE claims SET
                corroboration_level = 'rejected',
                embedding = NULL,
                evidence_text = '[ERASED]',
                sanitized_text = NULL,
                subject_entity = '[ERASED]',
                predicate = '[ERASED]',
                object_entity = NULL,
                object_value = NULL,
                employee_id = NULL,
                user_id = NULL,
                session_id = NULL,
                resolution_note = NULL,
                resolved_by_user_id = NULL,
                resolver_user_id = NULL,
                disputed_by_claim_id = NULL,
                tags = '{}',
                updated_at = now()
            WHERE id = $1
        """, claim_id)

        # Clean related interview session
        if pre_session_id:
            await conn.execute(
                "UPDATE interview_sessions SET rollup = '[Session data erased per GDPR request]' "
                "WHERE id = $1", pre_session_id,
            )
            sess = await conn.fetchrow(
                "SELECT dossier FROM interview_sessions WHERE id = $1", pre_session_id
            )
            if sess and sess["dossier"]:
                dossier = sess["dossier"]
                if isinstance(dossier, str):
                    dossier = json.loads(dossier)
                dossier.pop("turn_texts", None)
                dossier.pop("entities_seen", None)
                await conn.execute(
                    "UPDATE interview_sessions SET dossier = $1::jsonb WHERE id = $2",
                    json.dumps(dossier), pre_session_id,
                )

        await conn.execute(
            "INSERT INTO audit_log (user_id, action, resource, resource_id, details) "
            "VALUES ($1, 'gdpr_erase', 'claim', $2, $3::jsonb)",
            requester_id, str(claim_id),
            json.dumps({"reason_code": reason_code}),
        )


async def run_retention_expiry(pool, project_id: int) -> dict:
    """Auto-expire claims past retention_days. Bounded + idempotent."""
    async with pool.acquire() as conn:
        lock_key = int(hashlib.sha256(
            f"retention_expiry:{project_id}".encode()
        ).hexdigest()[:15], 16)

        async with conn.transaction():
            acquired = await conn.fetchval(
                "SELECT pg_try_advisory_xact_lock($1)", lock_key
            )
            if not acquired:
                return {"error": "already_running"}

            row = await conn.fetchrow(
                "SELECT config FROM org_settings WHERE project_id = $1", project_id
            )
            if row is None:
                return {"expired": 0, "reason": "no_org_settings"}
            config = row["config"]
            if isinstance(config, str):
                config = json.loads(config)
            retention = config.get("retention", {})
            days = retention.get("retention_days")
            auto = retention.get("auto_expiry", False)

            if not auto or not days or days <= 0:
                return {"expired": 0, "reason": "auto_expiry_disabled"}

            expired_claims = await conn.fetch("""
                SELECT id FROM claims
                WHERE project_id = $1
                  AND corroboration_level != 'rejected'
                  AND created_at < now() - ($2 || ' days')::interval
                LIMIT $3
            """, project_id, str(days), MAX_EXPIRY_BATCH)

            count = 0
            for c in expired_claims:
                already = await conn.fetchval(
                    "SELECT 1 FROM audit_log WHERE action = 'gdpr_erase' "
                    "AND resource = 'claim' AND resource_id = $1",
                    str(c["id"]),
                )
                if already:
                    continue
                await gdpr_erase_claim(conn, c["id"], None, "retention_expiry")
                count += 1

            if count > 0:
                await conn.execute(
                    "INSERT INTO cell_runs (cell_type, agent_id, model, metrics, status, finished_at) "
                    "VALUES ('retention_expiry', 1, 'n/a', $1::jsonb, 'completed', now())",
                    json.dumps({"project_id": project_id, "expired": count}),
                )

    return {"expired": count}


@router.post("/my-claims/{claim_id}/request-deletion")
async def request_deletion(
    claim_id: UUID,
    body: DeletionRequestCreate = DeletionRequestCreate(),
    actor: dict = Depends(get_current_user),
):
    """Employee requests deletion of own claim."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        claim = await conn.fetchrow(
            "SELECT id, project_id, employee_id, corroboration_level FROM claims WHERE id = $1",
            claim_id,
        )
        if claim is None:
            raise HTTPException(404, "claim not found")

        await check_access(conn, actor, claim["project_id"], "employee")
        actor_id = int(actor["sub"])

        if claim["employee_id"] != actor_id:
            raise HTTPException(403, "you can only request deletion of your own claims")

        if claim["corroboration_level"] == "rejected":
            raise HTTPException(409, "claim already erased/rejected")

        existing = await conn.fetchval(
            "SELECT 1 FROM deletion_requests WHERE claim_id = $1 AND status = 'pending'",
            claim_id,
        )
        if existing:
            raise HTTPException(409, "deletion request already pending")

        req_id = await conn.fetchval("""
            INSERT INTO deletion_requests (project_id, claim_id, requested_by, reason)
            VALUES ($1, $2, $3, $4) RETURNING id
        """, claim["project_id"], claim_id, actor_id, body.reason)

        return {"id": str(req_id), "status": "pending", "claim_id": str(claim_id)}


@router.get("/claims/deletion-requests")
async def list_deletion_requests(
    project_id: int = Query(..., gt=0),
    actor: dict = Depends(get_current_user),
):
    """List pending deletion requests. Curator/admin only."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await check_access(conn, actor, project_id, "curator")

        rows = await conn.fetch("""
            SELECT dr.id, dr.claim_id, dr.requested_by, dr.reason,
                   dr.status, dr.created_at, u.name AS requester_name
            FROM deletion_requests dr
            LEFT JOIN users u ON u.id = dr.requested_by
            WHERE dr.project_id = $1 AND dr.status = 'pending'
            ORDER BY dr.created_at ASC
        """, project_id)

    return [
        {
            "id": str(r["id"]),
            "claim_id": str(r["claim_id"]),
            "requested_by": r["requested_by"],
            "requester_name": r["requester_name"],
            "reason": r["reason"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


@router.put("/claims/deletion-requests/{request_id}/review")
async def review_deletion_request(
    request_id: UUID,
    body: ReviewBody,
    actor: dict = Depends(get_current_user),
):
    """Approve or reject a deletion request. Curator/admin only."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        req = await conn.fetchrow(
            "SELECT id, project_id, claim_id, status FROM deletion_requests WHERE id = $1",
            request_id,
        )
        if req is None:
            raise HTTPException(404, "deletion request not found")
        if req["status"] != "pending":
            raise HTTPException(409, f"request already {req['status']}")

        await check_access(conn, actor, req["project_id"], "curator")
        actor_id = int(actor["sub"])

        if body.decision == "approve":
            async with conn.transaction():
                await gdpr_erase_claim(conn, req["claim_id"], actor_id, "employee_request")
                await conn.execute(
                    "UPDATE deletion_requests SET status = 'approved', "
                    "reviewed_by = $1, resolved_at = now(), reason = NULL WHERE id = $2",
                    actor_id, request_id,
                )
        else:
            await conn.execute(
                "UPDATE deletion_requests SET status = 'rejected', "
                "reviewed_by = $1, resolved_at = now() WHERE id = $2",
                actor_id, request_id,
            )

        await conn.execute(
            "INSERT INTO audit_log (user_id, action, resource, resource_id, details) "
            "VALUES ($1, 'review_deletion', 'deletion_request', $2, $3::jsonb)",
            actor_id, str(request_id),
            json.dumps({"decision": body.decision, "claim_id": str(req["claim_id"]),
                         "note": body.note}),
        )

        return {"id": str(request_id), "status": body.decision + "d",
                "claim_id": str(req["claim_id"])}
