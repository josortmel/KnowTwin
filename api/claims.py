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
    "single_source": {"corroborated", "rejected"},
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


def _claim_row_to_response(row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "agent_id": row["agent_id"],
        "project_id": row["project_id"],
        "subject_entity": row["subject_entity"],
        "predicate": row["predicate"],
        "object_entity": row["object_entity"],
        "object_value": row["object_value"],
        "evidence_text": row["evidence_text"],
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

    return _claim_row_to_response(row)


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
        "items": [_claim_row_to_response(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


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
            return _claim_row_to_response(current)

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

    return _claim_row_to_response(row)


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
            "SELECT corroboration_level, source_type, embedding FROM claims WHERE id = $1",
            claim_id,
        )
        if not current:
            raise HTTPException(404, "claim not found")

        cur_level = current["corroboration_level"]

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

        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details)
               VALUES ($1, 'promote_claim', 'claim', $2, $3::jsonb)""",
            int(actor["sub"]), str(claim_id),
            json.dumps({"old_level": cur_level, "new_level": new_level}),
        )

    return _claim_row_to_response(row)
