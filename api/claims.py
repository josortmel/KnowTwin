"""KnowTwin claim endpoints — create + promote (embed gate).

Embed gate rule (single source of truth): a claim carries an embedding IFF
corroboration_level IN ('single_source','corroborated','corroborated_by_employee','validated').
Explicit IN-list, NEVER >=. draft/rejected → embedding NULL. disputed IS embedded
(dispute_state is display metadata, not an index gate).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from auth import get_current_user
from db import get_pool
from embeddings_client import embed_text
from permissions import no_null_bytes as _no_null_bytes

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

MAX_EVIDENCE_LEN = 16_000
MAX_TAGS = 50
MAX_TAG_LEN = 200

SourceType = Literal["document", "interview", "curator"]
Sensitivity = Literal["public", "team", "restricted"]


class ClaimCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_entity: str = Field(..., min_length=1, max_length=500)
    predicate: str = Field(..., min_length=1, max_length=200)
    object_entity: Optional[str] = Field(None, max_length=500)
    object_value: Optional[str] = Field(None, max_length=2000)
    evidence_text: str = Field(..., min_length=1, max_length=MAX_EVIDENCE_LEN)
    source_type: SourceType
    project_id: int
    source_id: Optional[UUID] = None
    source_date: Optional[datetime] = None
    employee_id: Optional[int] = None
    session_id: Optional[UUID] = None
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


@router.post("", response_model=ClaimResponse, status_code=201)
async def create_claim(body: ClaimCreate, actor: dict = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        agent_id = None
        if body.agent_identifier:
            agent_row = await conn.fetchrow(
                "SELECT id FROM agents WHERE identifier = $1", body.agent_identifier
            )
            if not agent_row:
                raise HTTPException(422, f"agent '{body.agent_identifier}' not found")
            agent_id = agent_row["id"]

        row = await conn.fetchrow(
            """
            INSERT INTO claims
            (user_id, agent_id, project_id,
             subject_entity, predicate, object_entity, object_value,
             evidence_text, source_type, source_id, source_date,
             employee_id, session_id, tags, sensitivity, criticality)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            RETURNING *
            """,
            int(actor["sub"]), agent_id, body.project_id,
            body.subject_entity, body.predicate, body.object_entity, body.object_value,
            body.evidence_text, body.source_type,
            str(body.source_id) if body.source_id else None,
            body.source_date,
            body.employee_id, str(body.session_id) if body.session_id else None,
            body.tags, body.sensitivity, body.criticality,
        )

    return _claim_row_to_response(row)


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

    return _claim_row_to_response(row)
