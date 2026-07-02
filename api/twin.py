"""KnowTwin Twin query pipeline — GAMR adapted to claims.

Retrieval: semantic (claims.embedding) → graph expansion → rerank.
Visibility: shared predicate re-applied at EVERY stage (GC1 fix).
Employee DENIED /twin/query (403).
"""
from __future__ import annotations

import html
import json
import logging
import secrets
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import get_current_user
from db import get_pool
from permissions import check_access
from claims import _visibility_sql, _EMBED_LEVELS

log = logging.getLogger("knowtwin.twin")

router = APIRouter(prefix="/twin", tags=["twin"])

_MAX_RESULTS = 20
_GRAPH_HOP_DEPTH = 2
_MAX_SEED_ENTITIES = 30


class TwinQuery(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    project_id: int = Field(..., gt=0)


class TwinSource(BaseModel):
    claim_id: str
    subject_entity: str
    predicate: str
    evidence_text: str
    sensitivity: str
    corroboration_level: str
    dispute_state: str
    criticality: float
    score: float


class DisputeGroup(BaseModel):
    subject_entity: str
    predicate: str
    versions: list[TwinSource]


class TwinResponse(BaseModel):
    answer: str
    sources: list[TwinSource]
    disputes: list[DisputeGroup]
    coverage_context: Optional[dict] = None


def _sanitize_for_llm(text: str, delimiter: str) -> str:
    """Wrap untrusted text with delimiter to prevent injection."""
    escaped = html.escape(text, quote=True)
    return f"{delimiter}\n{escaped}\n{delimiter}"


async def _semantic_search(conn, query_text: str, project_id: int,
                           role: str, actor_id: int, limit: int = _MAX_RESULTS) -> list[dict]:
    """Stage 1: vector similarity on claims.embedding with visibility predicate."""
    from embeddings_client import embed_text
    try:
        query_vec = await embed_text(query_text, "query")
    except Exception:
        return []

    if query_vec is None:
        return []

    vis_sql, vis_params = _visibility_sql(role, actor_id, 3)

    query = f"""
        SELECT c.id, c.subject_entity, c.predicate, c.object_entity, c.object_value,
               c.evidence_text, c.sensitivity, c.corroboration_level, c.dispute_state,
               c.criticality, c.doc_strength,
               1 - (c.embedding <=> $1::vector) AS similarity
        FROM claims c
        WHERE c.project_id = $2
          AND c.embedding IS NOT NULL
          AND ({vis_sql})
        ORDER BY c.embedding <=> $1::vector
        LIMIT {limit}
    """

    params = [str(query_vec), project_id, *vis_params]
    rows = await conn.fetch(query, *params)
    return [dict(r) for r in rows]


async def _text_search(conn, query_text: str, project_id: int,
                       role: str, actor_id: int, exclude_ids: set = None,
                       limit: int = _MAX_RESULTS) -> list[dict]:
    """Stage 2: text search fallback — ILIKE on subject_entity + evidence_text."""
    words = [w.strip() for w in query_text.split() if len(w.strip()) >= 3]
    if not words:
        return []

    idx = 2
    params: list = [project_id]

    vis_sql, vis_params = _visibility_sql(role, actor_id, idx)
    params.extend(vis_params)
    idx += len(vis_params)

    word_conds = []
    for w in words:
        word_conds.append(
            f"(c.subject_entity ILIKE ${idx} OR c.evidence_text ILIKE ${idx})"
        )
        params.append(f"%{w}%")
        idx += 1

    query = f"""
        SELECT c.id, c.subject_entity, c.predicate, c.object_entity, c.object_value,
               c.evidence_text, c.sensitivity, c.corroboration_level, c.dispute_state,
               c.criticality, c.doc_strength,
               0.5 AS similarity
        FROM claims c
        WHERE c.project_id = $1
          AND c.corroboration_level IN ('single_source','corroborated','corroborated_by_employee','validated')
          AND ({vis_sql})
          AND ({' OR '.join(word_conds)})
        LIMIT {limit}
    """

    rows = await conn.fetch(query, *params)
    exclude = exclude_ids or set()
    return [dict(r) for r in rows if str(r["id"]) not in exclude]


async def _graph_expand(conn, seed_claim_ids: list, project_id: int,
                        role: str, actor_id: int) -> list[dict]:
    """Stage 4: graph expansion — find entities in seed claims, discover more claims.

    CRITICAL: re-applies visibility predicate to ALL discovered claims (GC1 fix).
    """
    if not seed_claim_ids:
        return []

    entity_rows = await conn.fetch("""
        SELECT DISTINCT cel.entity_node_id, n.name AS entity_name
        FROM claim_entity_links cel
        JOIN nodes n ON n.id = cel.entity_node_id
        WHERE cel.claim_id = ANY($1::uuid[])
    """, seed_claim_ids)

    if not entity_rows:
        return []

    entity_ids = [r["entity_node_id"] for r in entity_rows]
    if len(entity_ids) > _MAX_SEED_ENTITIES:
        entity_ids = entity_ids[:_MAX_SEED_ENTITIES]

    vis_sql, vis_params = _visibility_sql(role, actor_id, 4)

    discovered = await conn.fetch(f"""
        SELECT DISTINCT c.id, c.subject_entity, c.predicate, c.object_entity, c.object_value,
               c.evidence_text, c.sensitivity, c.corroboration_level, c.dispute_state,
               c.criticality, c.doc_strength,
               0.3 AS similarity
        FROM claim_entity_links cel
        JOIN claims c ON c.id = cel.claim_id
        WHERE cel.entity_node_id = ANY($1::bigint[])
          AND c.project_id = $2
          AND c.id != ALL($3::uuid[])
          AND ({vis_sql})
        LIMIT {_MAX_RESULTS}
    """, entity_ids, project_id, seed_claim_ids, *vis_params)

    return [dict(r) for r in discovered]


def _assemble_disputes(claims: list[dict]) -> list[DisputeGroup]:
    """Group disputed claims by subject+predicate, order by doc_strength."""
    groups: dict[tuple, list[dict]] = {}
    for c in claims:
        if c["dispute_state"] == "disputed":
            key = (c["subject_entity"], c["predicate"])
            groups.setdefault(key, []).append(c)

    result = []
    for (subj, pred), versions in groups.items():
        sorted_v = sorted(versions, key=lambda x: x.get("doc_strength") or 0, reverse=True)
        result.append(DisputeGroup(
            subject_entity=subj,
            predicate=pred,
            versions=[TwinSource(
                claim_id=str(v["id"]),
                subject_entity=v["subject_entity"],
                predicate=v["predicate"],
                evidence_text=v["evidence_text"],
                sensitivity=v["sensitivity"],
                corroboration_level=v["corroboration_level"],
                dispute_state=v["dispute_state"],
                criticality=v.get("criticality", 0.5),
                score=float(v.get("similarity", 0)),
            ) for v in sorted_v],
        ))
    return result


def _format_answer(question: str, claims: list[dict]) -> str:
    """Format answer with mandatory citations. No LLM — deterministic for now."""
    if not claims:
        return "Insufficient information — no matching claims found for this question."

    delimiter = f"__KT_{secrets.token_hex(8)}__"
    safe_q = _sanitize_for_llm(question, delimiter)

    lines = []
    for i, c in enumerate(claims, 1):
        subj = c["subject_entity"]
        pred = c["predicate"]
        ev = c["evidence_text"][:200]
        dispute = ""
        if c["dispute_state"] == "disputed":
            dispute = " [DISPUTED]"
        elif c["dispute_state"] == "resolved_against":
            continue
        lines.append(f"[{i}] {subj} — {pred}: {ev}{dispute}")

    if not lines:
        return "Insufficient information — no matching claims found for this question."

    return "Based on available claims:\n\n" + "\n".join(lines)


@router.post("/query", response_model=TwinResponse)
async def twin_query(
    body: TwinQuery,
    actor: dict = Depends(get_current_user),
):
    """Twin query — read-only retrieval with citations."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        role = await check_access(conn, actor, body.project_id, "consumer")

        if role == "employee":
            raise HTTPException(403, "employees cannot query the twin")

        actor_id = int(actor["sub"])

        semantic_results = await _semantic_search(
            conn, body.question, body.project_id, role, actor_id
        )

        seen_ids = {str(r["id"]) for r in semantic_results}

        text_results = await _text_search(
            conn, body.question, body.project_id, role, actor_id,
            exclude_ids=seen_ids,
        )
        for tr in text_results:
            if str(tr["id"]) not in seen_ids:
                semantic_results.append(tr)
                seen_ids.add(str(tr["id"]))

        seed_ids = [r["id"] for r in semantic_results]
        graph_results = await _graph_expand(
            conn, seed_ids, body.project_id, role, actor_id
        )

        for gr in graph_results:
            if str(gr["id"]) not in seen_ids:
                semantic_results.append(gr)
                seen_ids.add(str(gr["id"]))

        all_claims = [
            c for c in semantic_results
            if c["dispute_state"] != "resolved_against"
        ]

        sources = [
            TwinSource(
                claim_id=str(c["id"]),
                subject_entity=c["subject_entity"],
                predicate=c["predicate"],
                evidence_text=c["evidence_text"],
                sensitivity=c["sensitivity"],
                corroboration_level=c["corroboration_level"],
                dispute_state=c["dispute_state"],
                criticality=c.get("criticality", 0.5),
                score=float(c.get("similarity", 0)),
            )
            for c in all_claims
        ]

        disputes = _assemble_disputes(all_claims)
        answer = _format_answer(body.question, all_claims)

        return TwinResponse(
            answer=answer,
            sources=sources,
            disputes=disputes,
        )
