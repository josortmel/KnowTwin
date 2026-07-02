"""KnowTwin claim CRUD — create/read/list/update/soft-delete with embed gate.

Embed gate rule (single source of truth): a claim carries an embedding IFF
corroboration_level IN ('single_source','corroborated','corroborated_by_employee','validated').
Explicit IN-list, NEVER >=. draft/rejected → embedding NULL. disputed IS embedded
(dispute_state is display metadata, not an index gate).

Visibility predicate (BQ-2):
  consumer → corroboration_level IN allowed-list AND sensitivity IN ('public','team')
  employee → employee_id = actor (own claims, all sensitivities)
  curator/admin → all claims in project
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from auth import get_current_user
from db import get_pool
from embeddings_client import embed_text
from permissions import check_access, no_null_bytes as _no_null_bytes

log = logging.getLogger("knowtwin.claims")

router = APIRouter(prefix="/claims", tags=["claims"])

_EMBED_LEVELS = frozenset({
    "single_source", "corroborated",
    "corroborated_by_employee", "validated",
})

_VALID_TRANSITIONS = {
    "draft": {"single_source", "rejected"},
    "single_source": {"corroborated", "corroborated_by_employee", "rejected"},
    "corroborated": {"corroborated_by_employee", "rejected"},
    "corroborated_by_employee": {"validated", "rejected"},
    "validated": {"rejected"},
    "rejected": set(),
}

_SENSITIVITY_RANK = {"public": 0, "team": 1, "restricted": 2}

MAX_EVIDENCE_LEN = 16_000
MAX_TAGS = 50
MAX_TAG_LEN = 200

SourceType = Literal["document", "interview", "curator"]
Sensitivity = Literal["public", "team", "restricted"]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ClaimCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_entity: str = Field(..., min_length=1, max_length=500)
    predicate: str = Field(..., min_length=1, max_length=200)
    object_entity: Optional[str] = Field(None, max_length=500)
    object_value: Optional[str] = Field(None, max_length=2000)
    evidence_text: str = Field(..., min_length=1, max_length=MAX_EVIDENCE_LEN)
    source_type: SourceType
    project_id: int
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    sensitivity: Sensitivity = "restricted"
    criticality: float = Field(0.5, ge=0.0, le=1.0)
    agent_identifier: Optional[str] = Field(None, min_length=1, max_length=128)

    @field_validator("evidence_text")
    @classmethod
    def _v_evidence(cls, v: str) -> str:
        return _no_null_bytes(v, "evidence_text")

    @field_validator("tags")
    @classmethod
    def _v_tags(cls, v: list[str]) -> list[str]:
        for t in v:
            if len(t) > MAX_TAG_LEN:
                raise ValueError(f"tag exceeds max length {MAX_TAG_LEN}")
            _no_null_bytes(t, "tag")
        return v


class ClaimUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensitivity: Optional[Sensitivity] = None
    dispute_state: Optional[Literal["undisputed", "disputed", "resolved_in_favor", "resolved_against"]] = None
    tags: Optional[list[str]] = Field(None, max_length=MAX_TAGS)
    resolution_note: Optional[str] = Field(None, max_length=2000)

    @field_validator("tags")
    @classmethod
    def _v_tags(cls, v):
        if v is None:
            return v
        for t in v:
            if len(t) > MAX_TAG_LEN:
                raise ValueError(f"tag exceeds max length {MAX_TAG_LEN}")
            _no_null_bytes(t, "tag")
        return v


class PromoteRequest(BaseModel):
    new_level: str
    force: bool = False


class ClaimResponse(BaseModel):
    id: UUID
    user_id: Optional[int]
    agent_id: Optional[int]
    project_id: int
    subject_entity: str
    predicate: str
    object_entity: Optional[str]
    object_value: Optional[str]
    evidence_text: str
    source_type: str
    corroboration_level: str
    dispute_state: str
    freshness_state: str
    sensitivity: str
    trust_tier: int
    confidence: float
    criticality: float
    has_embedding: bool
    tags: list[str]
    created_at: datetime
    updated_at: datetime


class ClaimListResponse(BaseModel):
    items: list[ClaimResponse]
    total: int
    limit: int
    offset: int


def _claim_row_to_response(row, role: str = "admin") -> dict:
    from permissions import render_evidence
    evidence = render_evidence(role, row["evidence_text"], row.get("sanitized_text"))
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "agent_id": row["agent_id"],
        "project_id": row["project_id"],
        "subject_entity": row["subject_entity"],
        "predicate": row["predicate"],
        "object_entity": row["object_entity"],
        "object_value": row["object_value"],
        "evidence_text": evidence,
        "source_type": row["source_type"],
        "corroboration_level": row["corroboration_level"],
        "dispute_state": row["dispute_state"],
        "freshness_state": row["freshness_state"],
        "sensitivity": row["sensitivity"],
        "trust_tier": row["trust_tier"],
        "confidence": row["confidence"],
        "criticality": row["criticality"],
        "has_embedding": row["embedding"] is not None,
        "tags": row["tags"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _visibility_sql(role: str, actor_id: int, param_offset: int) -> tuple[str, list]:
    """Return (WHERE fragment, params) for role-based claim visibility.

    Parameterized — no value interpolation.
    """
    if role in ("admin", "curator"):
        return "TRUE", []
    if role == "employee":
        return f"c.employee_id = ${param_offset}", [actor_id]
    return (
        "c.corroboration_level IN ('single_source','corroborated',"
        "'corroborated_by_employee','validated') "
        "AND c.sensitivity IN ('public','team')",
        [],
    )


# ---------------------------------------------------------------------------
# POST /claims — create
# ---------------------------------------------------------------------------

@router.post("", response_model=ClaimResponse, status_code=201)
async def create_claim(body: ClaimCreate, actor: dict = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await check_access(conn, actor, body.project_id, "curator")

        agent_id = None
        if body.agent_identifier:
            agent_row = await conn.fetchrow(
                "SELECT id FROM agents WHERE identifier = $1", body.agent_identifier
            )
            if not agent_row:
                raise HTTPException(422, f"agent '{body.agent_identifier}' not found")
            agent_id = agent_row["id"]

        sensitivity = body.sensitivity
        if sensitivity == "restricted":
            from org_settings import get_sanitization_default
            node_row = await conn.fetchrow(
                "SELECT type FROM nodes WHERE name = $1", body.subject_entity
            )
            if node_row and node_row["type"]:
                default_sens = await get_sanitization_default(conn, body.project_id, node_row["type"])
                if default_sens:
                    sensitivity = default_sens

        row = await conn.fetchrow(
            """
            INSERT INTO claims
            (user_id, agent_id, project_id,
             subject_entity, predicate, object_entity, object_value,
             evidence_text, source_type, tags, sensitivity, criticality)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            RETURNING *
            """,
            int(actor["sub"]), agent_id, body.project_id,
            body.subject_entity, body.predicate, body.object_entity, body.object_value,
            body.evidence_text, body.source_type,
            body.tags, sensitivity, body.criticality,
        )

    return _claim_row_to_response(row)


# ---------------------------------------------------------------------------
# GET /claims/export — csv|json with role+sensitivity gating (P2.9)
# Must be registered before /{claim_id} to avoid path capture.
# ---------------------------------------------------------------------------

def _csv_safe(val: str) -> str:
    """Prefix formula-injection-prone cells with single quote."""
    if not val:
        return val
    if val[0] in ("\t", "\r"):
        return "'" + val
    stripped = val.lstrip()
    if stripped and stripped[0] in ("=", "+", "-", "@"):
        return "'" + val
    return val


@router.get("/export")
async def export_claims(
    project_id: int = Query(..., gt=0),
    format: Literal["csv", "json"] = Query("json"),
    actor: dict = Depends(get_current_user),
):
    from fastapi.responses import Response as RawResponse
    pool = await get_pool()
    async with pool.acquire() as conn:
        role = await check_access(conn, actor, project_id, "consumer")
        actor_id = int(actor["sub"])

        vis_sql, vis_params = _visibility_sql(role, actor_id, 2)
        params = [project_id, *vis_params]

        rows = await conn.fetch(f"""
            SELECT id, subject_entity, predicate, object_value, evidence_text,
                   sanitized_text, source_type, sensitivity, corroboration_level,
                   dispute_state, freshness_state, criticality, trust_tier,
                   created_at, updated_at
            FROM claims c
            WHERE c.project_id = $1 AND ({vis_sql})
            ORDER BY c.created_at DESC
        """, *params)

    from permissions import render_evidence

    if format == "json":
        items = []
        for r in rows:
            d = dict(r)
            d["id"] = str(d["id"])
            d["evidence_text"] = render_evidence(role, d["evidence_text"], d.get("sanitized_text"))
            d.pop("sanitized_text", None)
            d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
            d["updated_at"] = d["updated_at"].isoformat() if d["updated_at"] else None
            items.append(d)
        return items

    headers = [
        "id", "subject_entity", "predicate", "object_value", "evidence_text",
        "source_type", "sensitivity", "corroboration_level", "dispute_state",
        "freshness_state", "criticality", "trust_tier", "created_at", "updated_at",
    ]
    lines = [",".join(headers)]
    for r in rows:
        ev = render_evidence(role, r["evidence_text"], r.get("sanitized_text"))
        vals = [
            str(r["id"]),
            _csv_safe(r["subject_entity"] or ""),
            _csv_safe(r["predicate"] or ""),
            _csv_safe(r["object_value"] or ""),
            _csv_safe(ev.replace('"', '""') if ev else ""),
            r["source_type"] or "",
            r["sensitivity"] or "",
            r["corroboration_level"] or "",
            r["dispute_state"] or "",
            r["freshness_state"] or "",
            str(r["criticality"]),
            str(r["trust_tier"]),
            r["created_at"].isoformat() if r["created_at"] else "",
            r["updated_at"].isoformat() if r["updated_at"] else "",
        ]
        lines.append(",".join(f'"{v}"' for v in vals))

    csv_content = "\n".join(lines)
    return RawResponse(
        content=csv_content.encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=claims_export.csv"},
    )


# ---------------------------------------------------------------------------
# GET /claims/{id} — read single
# ---------------------------------------------------------------------------

@router.get("/{claim_id}", response_model=ClaimResponse)
async def get_claim(claim_id: UUID, actor: dict = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM claims WHERE id = $1", claim_id)
        if not row:
            raise HTTPException(404, "claim not found")

        role = await check_access(conn, actor, row["project_id"], "consumer")
        actor_id = int(actor["sub"])

        if role == "consumer":
            if row["corroboration_level"] not in _EMBED_LEVELS:
                raise HTTPException(404, "claim not found")
            if row["sensitivity"] not in ("public", "team"):
                raise HTTPException(404, "claim not found")
        elif role == "employee":
            if row["employee_id"] != actor_id:
                raise HTTPException(404, "claim not found")

    return _claim_row_to_response(row, role)


# ---------------------------------------------------------------------------
# GET /claims — list with filters
# ---------------------------------------------------------------------------

@router.get("", response_model=ClaimListResponse)
async def list_claims(
    project_id: int = Query(...),
    subject_entity: Optional[str] = Query(None),
    predicate_filter: Optional[str] = Query(None, alias="predicate"),
    corroboration_level: Optional[str] = Query(None),
    dispute_state: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actor: dict = Depends(get_current_user),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        role = await check_access(conn, actor, project_id, "consumer")
        actor_id = int(actor["sub"])

        conditions = ["c.project_id = $1"]
        params: list = [project_id]
        idx = 2

        vis_sql, vis_params = _visibility_sql(role, actor_id, idx)
        if vis_sql != "TRUE":
            conditions.append(f"({vis_sql})")
            params.extend(vis_params)
            idx += len(vis_params)

        if subject_entity:
            conditions.append(f"c.subject_entity = ${idx}")
            params.append(subject_entity)
            idx += 1
        if predicate_filter:
            conditions.append(f"c.predicate = ${idx}")
            params.append(predicate_filter)
            idx += 1
        if corroboration_level:
            conditions.append(f"c.corroboration_level = ${idx}")
            params.append(corroboration_level)
            idx += 1
        if dispute_state:
            conditions.append(f"c.dispute_state = ${idx}")
            params.append(dispute_state)
            idx += 1

        where = " AND ".join(conditions)

        total = await conn.fetchval(
            f"SELECT count(*) FROM claims c WHERE {where}", *params
        )

        params.append(limit)
        params.append(offset)
        rows = await conn.fetch(
            f"SELECT * FROM claims c WHERE {where} "
            f"ORDER BY c.created_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
            *params,
        )

    return {
        "items": [_claim_row_to_response(r, role) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# PUT /claims/batch — batch approve/reject/set_sensitivity (P2.9)
# Must be registered before /{claim_id} to avoid path capture.
# ---------------------------------------------------------------------------

_APPROVE_NEXT = {
    "draft": "single_source",
    "single_source": "corroborated",
    "corroborated": "corroborated_by_employee",
    "corroborated_by_employee": "validated",
}


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[UUID] = Field(..., min_length=1, max_length=200)
    action: Literal["approve", "reject", "set_sensitivity"]
    value: Optional[str] = None

    @field_validator("ids")
    @classmethod
    def _unique_ids(cls, v):
        if len(set(str(i) for i in v)) != len(v):
            raise ValueError("duplicate claim IDs not allowed")
        return v


@router.put("/batch")
async def batch_claims(body: BatchRequest, actor: dict = Depends(get_current_user)):
    pool = await get_pool()
    succeeded = []
    failed = []

    async with pool.acquire() as conn:
        for cid in body.ids:
            try:
                row = await conn.fetchrow(
                    "SELECT id, project_id, corroboration_level, source_type, "
                    "embedding, sensitivity, subject_entity, predicate, "
                    "object_value, object_entity FROM claims WHERE id = $1", cid,
                )
                if row is None:
                    failed.append({"id": str(cid), "error": "not_found"})
                    continue

                await check_access(conn, actor, row["project_id"], "curator")
                actor_id = int(actor["sub"])
                cur_level = row["corroboration_level"]

                if body.action == "approve":
                    next_level = _APPROVE_NEXT.get(cur_level)
                    if next_level is None:
                        failed.append({"id": str(cid),
                                       "error": f"no valid promotion from {cur_level}"})
                        continue
                    valid_next = _VALID_TRANSITIONS.get(cur_level, set())
                    if next_level not in valid_next:
                        failed.append({"id": str(cid),
                                       "error": f"transition {cur_level} not allowed"})
                        continue
                    if next_level == "validated" and row["source_type"] == "interview":
                        next_level = "corroborated_by_employee"
                        if cur_level == "corroborated_by_employee":
                            failed.append({"id": str(cid),
                                           "error": "interview_cap_reached"})
                            continue

                    async with conn.transaction():
                        if next_level in _EMBED_LEVELS and row["embedding"] is None:
                            try:
                                evidence = await conn.fetchval(
                                    "SELECT evidence_text FROM claims WHERE id = $1", cid)
                                vec = await embed_text(evidence, prompt_name="passage")
                                if vec is None:
                                    failed.append({"id": str(cid), "error": "embedding_failed"})
                                    continue
                                await conn.execute(
                                    "UPDATE claims SET corroboration_level = $1, "
                                    "embedding = $2::vector, updated_at = now() WHERE id = $3",
                                    next_level, str(vec), cid,
                                )
                            except HTTPException:
                                failed.append({"id": str(cid), "error": "embedding_unavailable"})
                                continue
                        else:
                            await conn.execute(
                                "UPDATE claims SET corroboration_level = $1, updated_at = now() WHERE id = $2",
                                next_level, cid,
                            )
                        # Materialize graph triple + entity links (SQL + AGE dual-write)
                        from graph import _ensure_node, _create_age_edge
                        subj_nid = await _ensure_node(conn, row["subject_entity"])
                        await conn.execute(
                            "INSERT INTO claim_entity_links (claim_id, entity_node_id) "
                            "VALUES ($1, $2) ON CONFLICT DO NOTHING",
                            cid, subj_nid,
                        )
                        obj_name = row.get("object_entity") or row.get("object_value")
                        if obj_name:
                            obj_nid = await _ensure_node(conn, obj_name)
                            await conn.execute(
                                "INSERT INTO claim_entity_links (claim_id, entity_node_id) "
                                "VALUES ($1, $2) ON CONFLICT DO NOTHING",
                                cid, obj_nid,
                            )
                            t_row = await conn.fetchrow(
                                "INSERT INTO triples (subject_id, predicate, object_id, claim_id) "
                                "VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING RETURNING id",
                                subj_nid, row["predicate"], obj_nid, cid,
                            )
                            if t_row is not None:
                                await _create_age_edge(conn, subj_nid, row["predicate"], obj_nid)
                        await conn.execute(
                            "INSERT INTO audit_log (user_id, action, resource, resource_id, details) "
                            "VALUES ($1, 'batch_approve', 'claim', $2, $3::jsonb)",
                            actor_id, str(cid),
                            json.dumps({"old_level": cur_level, "new_level": next_level}),
                        )
                    succeeded.append({"id": str(cid), "new_state": next_level})

                elif body.action == "reject":
                    if cur_level == "rejected":
                        failed.append({"id": str(cid), "error": "already_rejected"})
                        continue
                    async with conn.transaction():
                        await conn.execute("DELETE FROM triples WHERE claim_id = $1", cid)
                        await conn.execute(
                            "UPDATE claims SET corroboration_level = 'rejected', "
                            "embedding = NULL, updated_at = now() WHERE id = $1", cid,
                        )
                        await conn.execute(
                            "INSERT INTO audit_log (user_id, action, resource, resource_id, details) "
                            "VALUES ($1, 'batch_reject', 'claim', $2, $3::jsonb)",
                            actor_id, str(cid),
                            json.dumps({"old_level": cur_level}),
                        )
                    succeeded.append({"id": str(cid), "new_state": "rejected"})

                elif body.action == "set_sensitivity":
                    if body.value not in ("public", "team", "restricted"):
                        failed.append({"id": str(cid), "error": "invalid_sensitivity"})
                        continue
                    old_sens = row["sensitivity"]
                    async with conn.transaction():
                        await conn.execute(
                            "UPDATE claims SET sensitivity = $1, updated_at = now() WHERE id = $2",
                            body.value, cid,
                        )
                        await conn.execute(
                            "INSERT INTO audit_log (user_id, action, resource, resource_id, details) "
                            "VALUES ($1, 'batch_set_sensitivity', 'claim', $2, $3::jsonb)",
                            actor_id, str(cid),
                            json.dumps({"old": old_sens, "new": body.value}),
                        )
                    succeeded.append({"id": str(cid), "new_state": body.value})

            except HTTPException as he:
                failed.append({"id": str(cid), "error": he.detail})
            except Exception:
                failed.append({"id": str(cid), "error": "internal_error"})

    return {"succeeded": succeeded, "failed": failed}


# ---------------------------------------------------------------------------
# PUT /claims/{id} — update (curator/admin; employee tighten-only sensitivity)
# ---------------------------------------------------------------------------

@router.put("/{claim_id}", response_model=ClaimResponse)
async def update_claim(
    claim_id: UUID,
    body: ClaimUpdate,
    actor: dict = Depends(get_current_user),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        current = await conn.fetchrow("SELECT * FROM claims WHERE id = $1", claim_id)
        if not current:
            raise HTTPException(404, "claim not found")

        role = await check_access(conn, actor, current["project_id"], "employee")
        actor_id = int(actor["sub"])

        if role == "employee":
            if current["employee_id"] != actor_id:
                raise HTTPException(403, "employees can only update own claims")
            if body.dispute_state is not None or body.resolution_note is not None:
                raise HTTPException(403, "employees cannot change dispute_state")
            if body.sensitivity is not None:
                cur_rank = _SENSITIVITY_RANK[current["sensitivity"]]
                new_rank = _SENSITIVITY_RANK[body.sensitivity]
                if new_rank < cur_rank:
                    raise HTTPException(403, "employees can only tighten sensitivity")

        sets = []
        vals = []
        idx = 2

        if body.sensitivity is not None:
            sets.append(f"sensitivity = ${idx}")
            vals.append(body.sensitivity)
            idx += 1
        if body.dispute_state is not None:
            sets.append(f"dispute_state = ${idx}")
            vals.append(body.dispute_state)
            idx += 1
        if body.tags is not None:
            sets.append(f"tags = ${idx}")
            vals.append(body.tags)
            idx += 1
        if body.resolution_note is not None:
            sets.append(f"resolution_note = ${idx}")
            vals.append(body.resolution_note)
            idx += 1

        if not sets:
            return _claim_row_to_response(current, role)

        sets.append("updated_at = now()")
        set_clause = ", ".join(sets)

        row = await conn.fetchrow(
            f"UPDATE claims SET {set_clause} WHERE id = $1 RETURNING *",
            claim_id, *vals,
        )

        changes = {}
        if body.sensitivity is not None:
            changes["sensitivity"] = f"{current['sensitivity']}→{body.sensitivity}"
        if body.dispute_state is not None:
            changes["dispute_state"] = f"{current['dispute_state']}→{body.dispute_state}"
        if body.tags is not None:
            changes["tags"] = "updated"
        if body.resolution_note is not None:
            changes["resolution_note"] = "set"

        if changes:
            await conn.execute(
                """INSERT INTO audit_log (user_id, action, resource, resource_id, details)
                   VALUES ($1, 'update_claim', 'claim', $2, $3::jsonb)""",
                actor_id, str(claim_id), json.dumps(changes),
            )

    return _claim_row_to_response(row, role)


# ---------------------------------------------------------------------------
# DELETE /claims/{id} — soft delete
# ---------------------------------------------------------------------------

@router.delete("/{claim_id}", status_code=200)
async def soft_delete_claim(claim_id: UUID, actor: dict = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        current = await conn.fetchrow("SELECT * FROM claims WHERE id = $1", claim_id)
        if not current:
            raise HTTPException(404, "claim not found")
        if current["corroboration_level"] == "rejected":
            raise HTTPException(409, "claim already rejected")

        await check_access(conn, actor, current["project_id"], "curator")

        async with conn.transaction():
            await conn.execute("DELETE FROM triples WHERE claim_id = $1", claim_id)
            await conn.fetchrow(
                """
                UPDATE claims
                SET corroboration_level = 'rejected', embedding = NULL, updated_at = now()
                WHERE id = $1 RETURNING id
                """,
                claim_id,
            )
            await conn.execute(
                """INSERT INTO audit_log (user_id, action, resource, resource_id, details)
                   VALUES ($1, 'soft_delete_claim', 'claim', $2, $3::jsonb)""",
                int(actor["sub"]), str(claim_id),
                json.dumps({"previous_level": current["corroboration_level"]}),
            )

    return {"id": str(claim_id), "status": "rejected"}


# ---------------------------------------------------------------------------
# PUT /claims/{id}/promote — embed gate (P1.3, tested)
# ---------------------------------------------------------------------------

@router.put("/{claim_id}/promote", response_model=ClaimResponse)
async def promote_claim(claim_id: UUID, body: PromoteRequest, actor: dict = Depends(get_current_user)):
    new_level = body.new_level

    if new_level not in _VALID_TRANSITIONS and new_level not in {
        "draft", "single_source", "corroborated",
        "corroborated_by_employee", "validated", "rejected",
    }:
        raise HTTPException(422, f"invalid corroboration_level: {new_level}")

    pool = await get_pool()
    async with pool.acquire() as conn:
        claim_project = await conn.fetchval(
            "SELECT project_id FROM claims WHERE id = $1", claim_id,
        )
        if claim_project is None:
            raise HTTPException(404, "claim not found")
        await check_access(conn, actor, claim_project, "curator")

        current = await conn.fetchrow(
            "SELECT corroboration_level, source_type, embedding, evidence_text FROM claims WHERE id = $1",
            claim_id,
        )
        if not current:
            raise HTTPException(404, "claim not found")

        if current["evidence_text"] in (None, "[ERASED]"):
            raise HTTPException(409, "cannot promote erased claims")

        cur_level = current["corroboration_level"]

        # Force override: curator/admin can jump levels (bypass step-matrix)
        if body.force:
            role = await check_access(conn, actor, claim_project, "curator")
            if role not in ("curator", "admin"):
                raise HTTPException(403, "force override requires curator or admin role")
            if new_level == "validated" and current["source_type"] == "interview":
                raise HTTPException(
                    409,
                    "interview-only claims cannot reach 'validated' (CAP constraint). "
                    "Maximum: corroborated_by_employee.",
                )
        else:
            valid_next = _VALID_TRANSITIONS.get(cur_level, set())
            if new_level not in valid_next:
                raise HTTPException(
                    409,
                    f"invalid transition: {cur_level} → {new_level}. "
                    f"Allowed: {sorted(valid_next) or '(terminal)'}",
                )

            if new_level == "validated" and current["source_type"] == "interview":
                raise HTTPException(
                    409,
                    "interview-only claims cannot reach 'validated' (CAP constraint). "
                    "Maximum: corroborated_by_employee.",
                )

        if new_level in _EMBED_LEVELS:
            if current["embedding"] is not None:
                row = await conn.fetchrow(
                    """
                    UPDATE claims SET corroboration_level = $1, updated_at = now()
                    WHERE id = $2 RETURNING *
                    """,
                    new_level, claim_id,
                )
            else:
                evidence = await conn.fetchval(
                    "SELECT evidence_text FROM claims WHERE id = $1", claim_id
                )
                try:
                    vec = await embed_text(evidence, prompt_name="passage")
                except HTTPException:
                    log.warning("embed failed for claim %s — level unchanged", claim_id)
                    raise HTTPException(
                        503,
                        "embedding service unavailable — promotion deferred, claim unchanged",
                    )
                row = await conn.fetchrow(
                    """
                    UPDATE claims
                    SET corroboration_level = $1, embedding = $2::vector,
                        embedding_model = 'jina-v4', updated_at = now()
                    WHERE id = $3 RETURNING *
                    """,
                    new_level, vec, claim_id,
                )

        elif new_level == "rejected":
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM triples WHERE claim_id = $1", claim_id
                )
                row = await conn.fetchrow(
                    """
                    UPDATE claims
                    SET corroboration_level = 'rejected', embedding = NULL, updated_at = now()
                    WHERE id = $1 RETURNING *
                    """,
                    claim_id,
                )

        else:
            row = await conn.fetchrow(
                """
                UPDATE claims
                SET corroboration_level = $1, embedding = NULL, updated_at = now()
                WHERE id = $2 RETURNING *
                """,
                new_level, claim_id,
            )

        # Materialize claim as graph triple (SQL + AGE dual-write) + entity links
        if new_level != "rejected":
            from graph import _ensure_node, _create_age_edge
            subject_node_id = await _ensure_node(conn, row["subject_entity"])
            await conn.execute(
                "INSERT INTO claim_entity_links (claim_id, entity_node_id) "
                "VALUES ($1, $2) ON CONFLICT DO NOTHING",
                claim_id, subject_node_id,
            )
            object_name = row.get("object_entity") or row.get("object_value")
            if object_name:
                object_node_id = await _ensure_node(conn, object_name)
                await conn.execute(
                    "INSERT INTO claim_entity_links (claim_id, entity_node_id) "
                    "VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    claim_id, object_node_id,
                )
                triple_row = await conn.fetchrow(
                    "INSERT INTO triples (subject_id, predicate, object_id, claim_id) "
                    "VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING RETURNING id",
                    subject_node_id, row["predicate"], object_node_id, claim_id,
                )
                if triple_row is not None:
                    await _create_age_edge(conn, subject_node_id, row["predicate"], object_node_id)

        audit_action = "curator_override" if body.force else "promote_claim"
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details)
               VALUES ($1, $2, 'claim', $3, $4::jsonb)""",
            int(actor["sub"]), audit_action, str(claim_id),
            json.dumps({"old_level": cur_level, "new_level": new_level, "force": body.force}),
        )

    return _claim_row_to_response(row)


# ---------------------------------------------------------------------------
# GET /claims/{id}/audit — audit trail timeline (P2.9)
# ---------------------------------------------------------------------------

@router.get("/{claim_id}/audit")
async def claim_audit_trail(
    claim_id: UUID,
    actor: dict = Depends(get_current_user),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        claim_project = await conn.fetchval(
            "SELECT project_id FROM claims WHERE id = $1", claim_id
        )
        if claim_project is None:
            raise HTTPException(404, "claim not found")
        await check_access(conn, actor, claim_project, "curator")

        rows = await conn.fetch("""
            SELECT id, user_id, action, details, created_at
            FROM audit_log
            WHERE resource = 'claim' AND resource_id = $1
            ORDER BY created_at ASC
        """, str(claim_id))

    return [
        {
            "id": r["id"],
            "user_id": r["user_id"],
            "action": r["action"],
            "details": r["details"],
            "timestamp": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]
