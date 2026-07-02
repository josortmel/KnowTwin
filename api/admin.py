"""Endpoints administrativos — .7.

POST /admin/redistribute/memories: redistribuye memorias entre projects.
Used to redistribute memories from the default 'general' project to
organized workspaces and projects.

Razón del scope:
- Solo memorias: documentos están vacíos en Fase 1 (Fase 4 los activa).
- Sin grafo: nodes/triples NO tienen workspace_id en el schema — el grafo es
  global plataforma-wide en single-tenant mode (verificado init.sql §1.4-1.6).

Solo super (operación admin transversal). Multi-tenant fork: añadir CEO de la
org como autorizado para redistribuir solo dentro de su org (deuda).

Audit trail: 1 audit_log row batch por operación con resource_id=UUID + filter +
target + count + sample memory_ids. Granularidad apropiada single-tenant; en
multi-tenant fork con liability legal, 1 audit por memoria movida.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import Literal, Optional

import asyncpg

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from auth import get_current_user, require_super, require_super_or_ceo
from db import get_pool
from permissions import resolve_entity_org_ids, user_can_admin_operation
from entity_normalization import is_valid_entity_type, normalize_name

# import top-level de gliner_service
# documentado. graph.py usa lazy import por aislamiento de testing (mocking),
# NO por evitar import-time cost de torch — gliner_service.py NO importa
# torch/transformers al top-level (todo dentro de _ensure_loaded lazy). Por
# tanto el import-time cost de admin.py importando gliner_service es trivial
# (constantes + funciones helper, sin ML). Mantenemos top-level para que el
# f-string en Field description (linea 272) funcione en class-definition time.
from gliner_service import DEFAULT_LABELS, MODEL_NAME, extract_entities, load_dictionary_to_cache


router = APIRouter(prefix="/admin", tags=["admin"])


async def _check_admin_op(conn, actor: dict, operation: str, entity_name: str | None = None) -> None:
    """Check admin operation permission. Raises 403 if denied.

    Fail-closed: if entity_name provided but has no org links → 403 (not fall-through).
    """
    if actor.get("is_super"):
        return
    target_org = actor.get("organization_id")
    if entity_name:
        entity_orgs = await resolve_entity_org_ids(conn, entity_name)
        if len(entity_orgs) > 1:
            raise HTTPException(403, "entity spans multiple organizations — super required")
        if len(entity_orgs) == 0:
            raise HTTPException(403, "entity has no organization ownership — super required")
        target_org = entity_orgs.pop()
    if not await user_can_admin_operation(conn, actor, operation, target_org):
        raise HTTPException(403, "insufficient permissions for this admin operation")


# ---------------------------------------------------------------------------
# Pydantic
# ---------------------------------------------------------------------------

# Coherente con MemoryType de memories.py.
MemoryType = Literal["momento", "decision", "acuerdo", "tecnico", "descubrimiento", "observacion", "referencia"]


class RedistributeFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: int = Field(..., gt=0, description="Workspace origen — obligatorio.")
    project_id: int = Field(..., gt=0, description="Project origen — obligatorio.")
    agent_identifier: Optional[str] = Field(None, min_length=1, max_length=128)
    type: Optional[MemoryType] = None


class RedistributeTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: int = Field(..., gt=0)
    project_id: int = Field(..., gt=0)


class RedistributeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter: RedistributeFilter
    target: RedistributeTarget
    dry_run: bool = Field(False, description="Si true, devuelve count + sample sin UPDATE.")


class RedistributeResponse(BaseModel):
    dry_run: bool
    matched_count: int = Field(..., description="Cuántas memorias matchean el filter.")
    moved_count: int = Field(..., description="Cuántas se actualizaron (=matched si dry_run=false, 0 si dry_run=true).")
    sample_memory_ids: list[str] = Field(..., description="Hasta 5 IDs (UUID string) de las memorias afectadas.")
    audit_id: Optional[str] = Field(None, description="UUID del audit_log row si dry_run=false.")


# ---------------------------------------------------------------------------
# Attention Inbox (B2+B3 — dashboard backend)
# ---------------------------------------------------------------------------

_INBOX_CLASSES = frozenset({"stale_claims", "unconfirmed_relations", "pending_alias_candidates", "low_trust_documents", "pending_disputes", "pending_deletions"})


async def _inbox_query(conn, decision_class: str, actor: dict, limit: int = 0, offset: int = 0, count_only: bool = False):
    """Org-scoped inbox queries. Super sees all; CEO sees own org only."""
    is_super = actor.get("is_super")
    actor_org = actor.get("organization_id")

    _org_sub = "(SELECT p.id FROM projects p JOIN workspaces w ON w.id = p.workspace_id WHERE w.organization_id = %s)"

    if is_super:
        org_mem_c = ""
        org_mem_d = ""
        org_doc_c = ""
        org_doc_d = ""
        org_alias_c = ""
        org_alias_d = ""
        org_del_c = ""
        org_del_d = ""
    else:
        org_mem_c = f"AND m.project_id IN {_org_sub % '$1'}"
        org_mem_d = f"AND m.project_id IN {_org_sub % '$3'}"
        org_doc_c = f"AND d.project_id IN {_org_sub % '$1'}"
        org_doc_d = f"AND d.project_id IN {_org_sub % '$3'}"
        org_del_c = f"AND dr.project_id IN {_org_sub % '$1'}"
        org_del_d = f"AND dr.project_id IN {_org_sub % '$3'}"
        org_alias_c = f"""AND eac.id IN (
            SELECT eac2.id FROM entity_alias_candidates eac2
            JOIN nodes nn ON lower(nn.name) = lower(eac2.source_name)
            JOIN claim_entity_links cel ON cel.entity_node_id = nn.id
            JOIN claims mm ON mm.id = cel.claim_id
            JOIN projects pp ON pp.id = mm.project_id
            JOIN workspaces ww ON ww.id = pp.workspace_id
            WHERE ww.organization_id = $1)"""
        org_alias_d = f"""AND eac.id IN (
            SELECT eac2.id FROM entity_alias_candidates eac2
            JOIN nodes nn ON lower(nn.name) = lower(eac2.source_name)
            JOIN claim_entity_links cel ON cel.entity_node_id = nn.id
            JOIN claims mm ON mm.id = cel.claim_id
            JOIN projects pp ON pp.id = mm.project_id
            JOIN workspaces ww ON ww.id = pp.workspace_id
            WHERE ww.organization_id = $3)"""

    queries = {
        "stale_claims": {
            "count": f"SELECT count(*) FROM claims m WHERE m.freshness_state IN ('stale', 'dormant') {org_mem_c}",
            "detail": f"""
                SELECT m.id, m.evidence_text, m.source_type::text, m.freshness_state, m.created_at, m.updated_at,
                       a.identifier AS agent_identifier
                FROM claims m LEFT JOIN agents a ON a.id = m.agent_id
                WHERE m.freshness_state IN ('stale', 'dormant') {org_mem_d}
                ORDER BY m.updated_at ASC LIMIT $1 OFFSET $2""",
        },
        "unconfirmed_relations": {
            "count": f"""SELECT count(*) FROM related_documents rd
                JOIN documents d ON d.id = rd.source_id
                WHERE rd.confirmed_by IS NULL {org_doc_c}""",
            "detail": f"""
                SELECT rd.source_id, rd.target_id, rd.similarity, rd.detected_at,
                       ds.filename AS source_title, dt.filename AS target_title
                FROM related_documents rd
                JOIN documents ds ON ds.id = rd.source_id
                JOIN documents dt ON dt.id = rd.target_id
                WHERE rd.confirmed_by IS NULL
                AND ds.project_id IN {_org_sub % '$3' if not is_super else '(SELECT id FROM projects)'}
                AND dt.project_id IN {_org_sub % '$3' if not is_super else '(SELECT id FROM projects)'}
                ORDER BY rd.similarity DESC LIMIT $1 OFFSET $2""",
        },
        "pending_alias_candidates": {
            "count": f"SELECT count(*) FROM entity_alias_candidates eac WHERE eac.status = 'pending' {org_alias_c}",
            "detail": f"""
                SELECT eac.id, eac.source_name, n.name AS target_node_name,
                       eac.confidence, eac.occurrences, eac.first_seen, eac.last_seen
                FROM entity_alias_candidates eac
                JOIN nodes n ON n.id = eac.target_node_id
                WHERE eac.status = 'pending' {org_alias_d}
                ORDER BY eac.occurrences DESC, eac.confidence DESC LIMIT $1 OFFSET $2""",
        },
        "low_trust_documents": {
            "count": f"SELECT count(*) FROM documents d WHERE d.trust_tier = 0 AND d.status != 'deleted' {org_doc_c}",
            "detail": f"""
                SELECT d.id, d.filename, d.trust_tier, d.status,
                       d.created_at, d.last_indexed
                FROM documents d
                WHERE d.trust_tier = 0 AND d.status != 'deleted' {org_doc_d}
                ORDER BY d.created_at DESC LIMIT $1 OFFSET $2""",
        },
        "pending_disputes": {
            "count": f"SELECT count(*) FROM claims m WHERE m.dispute_state = 'disputed' {org_mem_c}",
            "detail": f"""
                SELECT m.id, m.evidence_text, m.source_type::text, m.dispute_state, m.created_at, m.updated_at,
                       a.identifier AS agent_identifier
                FROM claims m LEFT JOIN agents a ON a.id = m.agent_id
                WHERE m.dispute_state = 'disputed' {org_mem_d}
                ORDER BY m.updated_at ASC LIMIT $1 OFFSET $2""",
        },
        "pending_deletions": {
            "count": f"SELECT count(*) FROM deletion_requests dr WHERE dr.status = 'pending' {org_del_c}",
            "detail": f"""
                SELECT dr.id, dr.claim_id, dr.reason, dr.status, dr.created_at,
                       m.evidence_text, m.source_type::text
                FROM deletion_requests dr
                JOIN claims m ON m.id = dr.claim_id
                WHERE dr.status = 'pending' {org_del_d}
                ORDER BY dr.created_at ASC LIMIT $1 OFFSET $2""",
        },
    }

    q = queries[decision_class]
    if count_only:
        if is_super:
            return await conn.fetchval(q["count"])
        return await conn.fetchval(q["count"], actor_org)
    if is_super:
        total = await conn.fetchval(q["count"])
        rows = await conn.fetch(q["detail"], limit, offset)
    else:
        total = await conn.fetchval(q["count"], actor_org)
        rows = await conn.fetch(q["detail"], limit, offset, actor_org)
    return total, rows


@router.get("/attention-inbox/summary")
async def attention_inbox_summary(
    actor: dict = Depends(require_super_or_ceo),
) -> dict:
    """4 counts by decision class for Command Center dashboard. Org-scoped for CEO."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = {}
        for cls in _INBOX_CLASSES:
            result[cls] = await _inbox_query(conn, cls, actor, count_only=True)
    return {"classes": result, "total": sum(result.values())}


@router.get("/attention-inbox/details")
async def attention_inbox_details(
    decision_class: str = Query(..., description="One of: stale_claims, unconfirmed_relations, pending_alias_candidates, low_trust_documents, pending_disputes, pending_deletions"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    actor: dict = Depends(require_super_or_ceo),
) -> dict:
    """Paginated details for a single decision class. Org-scoped for CEO."""
    if decision_class not in _INBOX_CLASSES:
        raise HTTPException(400, f"invalid class, must be one of: {sorted(_INBOX_CLASSES)}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        total, rows = await _inbox_query(conn, decision_class, actor, limit=limit, offset=offset)
    items = [dict(r) for r in rows]
    for item in items:
        for k, v in item.items():
            if hasattr(v, 'isoformat'):
                item[k] = v.isoformat()
            elif isinstance(v, uuid.UUID):
                item[k] = str(v)
    return {"class": decision_class, "total": total, "items": items, "limit": limit, "offset": offset}


# ---------------------------------------------------------------------------
# Endpoint — redistribute
# ---------------------------------------------------------------------------

@router.post("/redistribute/memories", response_model=RedistributeResponse)
async def redistribute_memories(
    body: RedistributeRequest,
    actor: dict = Depends(require_super),
) -> RedistributeResponse:
    """Redistribuye memorias del filter al target. Atomic. Audit batch.

    Validaciones:
    - target.workspace_id y target.project_id existen.
    - target.project_id pertenece a target.workspace_id (no se acepta cross-ws
      assignment — sería incoherente y rompe la cascada de permisos).
    - Si filter coincide con target (mismo ws+project), 422 (no-op disfrazado).

    No valida que filter.workspace_id/project_id existan: si no existen, simplemente
    matched_count=0 — comportamiento natural del SELECT.
    """
    if (body.filter.workspace_id == body.target.workspace_id
            and body.filter.project_id == body.target.project_id):
        raise HTTPException(422, "filter and target are identical — nothing to redistribute")

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Validar target.
        target_ws = await conn.fetchval(
            "SELECT id FROM workspaces WHERE id = $1", body.target.workspace_id
        )
        if target_ws is None:
            raise HTTPException(422, "target.workspace_id does not exist")
        target_proj = await conn.fetchrow(
            "SELECT id, workspace_id FROM projects WHERE id = $1",
            body.target.project_id,
        )
        if target_proj is None:
            raise HTTPException(422, "target.project_id does not exist")
        if target_proj["workspace_id"] != body.target.workspace_id:
            raise HTTPException(
                422,
                "target.project_id does not belong to target.workspace_id",
            )

        # Construir WHERE del filter.
        where_parts = [
            "workspace_id = $1",
            "project_id = $2",
        ]
        params: list = [body.filter.workspace_id, body.filter.project_id]
        idx = 3

        if body.filter.agent_identifier is not None:
            # Resolver agent_identifier → agent_id (consistente con memories.py).
            agent_id = await conn.fetchval(
                "SELECT id FROM agents WHERE identifier = $1",
                body.filter.agent_identifier,
            )
            if agent_id is None:
                raise HTTPException(422, "filter.agent_identifier not found")
            where_parts.append(f"agent_id = ${idx}")
            params.append(agent_id)
            idx += 1

        if body.filter.type is not None:
            where_parts.append(f"type = ${idx}::memory_type")
            params.append(body.filter.type)
            idx += 1

        where_sql = " AND ".join(where_parts)

        # Sample + count.
        sample_rows = await conn.fetch(
            f"SELECT id FROM memories WHERE {where_sql} LIMIT 5",
            *params,
        )
        matched_count = await conn.fetchval(
            f"SELECT count(*) FROM memories WHERE {where_sql}",
            *params,
        )
        sample_ids = [str(r["id"]) for r in sample_rows]

        if body.dry_run:
            return RedistributeResponse(
                dry_run=True,
                matched_count=matched_count,
                moved_count=0,
                sample_memory_ids=sample_ids,
                audit_id=None,
            )

        if matched_count == 0:
            # Nada que mover. Audit log igual para forensics (intento documentado).
            # transacción explícita aunque sea 1 INSERT,
            # por simetría con el path matched>0 y para coherencia ante refactors.
            audit_uuid = str(uuid.uuid4())
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                    VALUES ($1, 'redistribute', 'memories_batch', $2, $3::jsonb, $4)
                    """,
                    int(actor["sub"]), audit_uuid,
                    json.dumps({
                        "filter": body.filter.model_dump(),
                        "target": body.target.model_dump(),
                        "matched_count": 0,
                        "moved_count": 0,
                        "sample_memory_ids": [],
                    }), actor.get("organization_id"),
                )
            return RedistributeResponse(
                dry_run=False,
                matched_count=0,
                moved_count=0,
                sample_memory_ids=[],
                audit_id=audit_uuid,
            )

        # Atomicidad: UPDATE + INSERT audit_log en una sola transacción.
        # Construimos el UPDATE con sus propios placeholders ($1=target_ws,
        # $2=target_proj, $3+ filter params). Más simple que reusar where_sql
        # con str.replace() que sufría aliasing entre placeholders.
        audit_uuid = str(uuid.uuid4())
        update_where_parts = ["workspace_id = $3", "project_id = $4"]
        update_params: list = [
            body.target.workspace_id, body.target.project_id,
            body.filter.workspace_id, body.filter.project_id,
        ]
        upd_idx = 5
        if body.filter.agent_identifier is not None:
            # agent_id ya resuelto arriba.
            update_where_parts.append(f"agent_id = ${upd_idx}")
            update_params.append(agent_id)
            upd_idx += 1
        if body.filter.type is not None:
            update_where_parts.append(f"type = ${upd_idx}::memory_type")
            update_params.append(body.filter.type)
            upd_idx += 1
        update_sql = (
            "UPDATE memories SET workspace_id = $1, project_id = $2, updated_at = now() "
            f"WHERE {' AND '.join(update_where_parts)}"
        )

        # capturar el moved_count REAL desde el
        # command tag de asyncpg. En single-tenant the platform owner no hay concurrencia
        # admin, pero un UPDATE puede afectar menos rows que matched_count si
        # alguien borra memorias entre el SELECT count y el UPDATE. Audit
        # registra ambos counts para forensics precisa.
        async with conn.transaction():
            update_result = await conn.execute(update_sql, *update_params)
            # asyncpg devuelve "UPDATE N" — parseamos el N final.
            moved_count_real = int(update_result.split()[-1])
            await conn.execute(
                """
                INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                VALUES ($1, 'redistribute', 'memories_batch', $2, $3::jsonb, $4)
                """,
                int(actor["sub"]), audit_uuid,
                json.dumps({
                    "filter": body.filter.model_dump(),
                    "target": body.target.model_dump(),
                    "matched_count": matched_count,
                    "moved_count": moved_count_real,
                    "sample_memory_ids": sample_ids,
                }), actor.get("organization_id"),
            )

    return RedistributeResponse(
        dry_run=False,
        matched_count=matched_count,
        moved_count=moved_count_real,
        sample_memory_ids=sample_ids,
        audit_id=audit_uuid,
    )


# ---------------------------------------------------------------------------
# — POST /admin/extract_entities (verificacion manual GLiNER)
# ---------------------------------------------------------------------------

class ExtractEntitiesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, max_length=32000, description="Texto a procesar.")
    labels: Optional[list[str]] = Field(
        None,
        description=f"Etiquetas a extraer. Default: {DEFAULT_LABELS}",
    )
    threshold: float = Field(0.7, ge=0.0, le=1.0, description="Score minimo (0-1). Default 0.7 (.")


class ExtractedEntity(BaseModel):
    text: str
    label: str
    start: int
    end: int
    score: float
    source: Literal["dictionary", "gliner"] = Field(
        ..., description="Provenance: 'dictionary' si vino del entity_dictionary override, 'gliner' si lo detecto el modelo."
    )


class ExtractEntitiesResponse(BaseModel):
    entities: list[ExtractedEntity]
    count: int
    latency_ms: float = Field(..., description="Wall-clock latency end-to-end.")
    model: str = Field(..., description="Nombre del modelo HF usado.")


@router.post("/extract_entities", response_model=ExtractEntitiesResponse)
async def admin_extract_entities(
    body: ExtractEntitiesRequest,
    actor: dict = Depends(require_super),
) -> ExtractEntitiesResponse:
    """Extrae entidades de un texto via GLiNER. Super-only — endpoint de
    verificacion para .

    El primer call carga el modelo (~10-30s). Calls siguientes ~200-500ms CPU.
    """
    t0 = time.time()
    entities = await extract_entities(
        text=body.text,
        labels=body.labels,
        threshold=body.threshold,
    )
    latency_ms = round((time.time() - t0) * 1000, 2)
    return ExtractEntitiesResponse(
        entities=[ExtractedEntity(**e) for e in entities],
        count=len(entities),
        latency_ms=latency_ms,
        model=MODEL_NAME,
    )


# ---------------------------------------------------------------------------
# — entity_dictionary CRUD + reload (super-only)
# ---------------------------------------------------------------------------

class EntityDictionaryEntry(BaseModel):
    """Entrada del entity_dictionary devuelta por GET endpoints."""
    id: int
    name: str
    name_normalized: str
    entity_type: str
    notes: Optional[str] = None
    created_by: Optional[int] = None
    created_at: str
    updated_at: str


class EntityDictionaryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200, pattern=r"^[\w\sáéíóúüÁÉÍÓÚÜñÑ.\-]+$",
                      description="Nombre original. Permite letras (acentuadas/ñ), digitos, espacios, guiones, puntos. NO comillas/punto-coma/barras.")
    entity_type: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z_]+$",
                             description="Tipo. Lowercase + underscore. Validado contra allowlist EntityType.")
    notes: Optional[str] = Field(None, max_length=500)


class EntityDictionaryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=200, pattern=r"^[\w\sáéíóúüÁÉÍÓÚÜñÑ.\-]+$")
    entity_type: Optional[str] = Field(None, min_length=1, max_length=50, pattern=r"^[a-z_]+$")
    notes: Optional[str] = Field(None, max_length=500)


def _row_to_dict_entry(row) -> EntityDictionaryEntry:
    return EntityDictionaryEntry(
        id=row["id"],
        name=row["name"],
        name_normalized=row["name_normalized"],
        entity_type=row["entity_type"],
        notes=row["notes"],
        created_by=row["created_by"],
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
    )


@router.post("/entity-dictionary", response_model=EntityDictionaryEntry, status_code=201)
async def create_dictionary_entry(
    body: EntityDictionaryCreate,
    actor: dict = Depends(require_super),
) -> EntityDictionaryEntry:
    """Crea entrada en entity_dictionary. Super-only.

    Validaciones (
    - entity_type contra allowlist EntityType (matiz adv-code: typo "persoana"
      → 422 antes que corromper graph_context silenciosamente).
    - Pattern Pydantic en name + entity_type (matiz adv-seg: anti emoji y
      caracteres extraños).
    - name_normalized se computa al INSERT (matiz coord, mismo en PUT).
    """
    if not is_valid_entity_type(body.entity_type):
        from entity_normalization import ALLOWED_ENTITY_TYPES
        raise HTTPException(
            422,
            f"entity_type '{body.entity_type}' not in allowlist: {sorted(ALLOWED_ENTITY_TYPES)}"
        )

    name_normalized = normalize_name(body.name)
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO entity_dictionary (name, name_normalized, entity_type, notes, created_by)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
                """,
                body.name, name_normalized, body.entity_type, body.notes, int(actor["sub"]),
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, f"name_normalized '{name_normalized}' already exists")
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'create_entity_dict', 'entity_dictionary', $2, $3::jsonb, $4)""",
            int(actor["sub"]), str(row["id"]),
            json.dumps({"name": body.name, "entity_type": body.entity_type}),
            actor.get("organization_id"),
        )
    return _row_to_dict_entry(row)


@router.get("/entity-dictionary", response_model=list[EntityDictionaryEntry])
async def list_dictionary_entries(
    entity_type: Optional[str] = None,
    actor: dict = Depends(require_super),
) -> list[EntityDictionaryEntry]:
    """Lista entradas del diccionario. Filtro opcional por entity_type."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if entity_type:
            rows = await conn.fetch(
                "SELECT * FROM entity_dictionary WHERE entity_type = $1 ORDER BY name",
                entity_type,
            )
        else:
            rows = await conn.fetch("SELECT * FROM entity_dictionary ORDER BY name")
    return [_row_to_dict_entry(r) for r in rows]


@router.put("/entity-dictionary/{entry_id}", response_model=EntityDictionaryEntry)
async def update_dictionary_entry(
    entry_id: int,
    body: EntityDictionaryUpdate,
    actor: dict = Depends(require_super),
) -> EntityDictionaryEntry:
    """Modifica entrada. Si se cambia name, recompute name_normalized
    (matiz coord vinculante)."""
    if body.name is None and body.entity_type is None and body.notes is None:
        raise HTTPException(400, "no fields to update")
    if body.entity_type is not None and not is_valid_entity_type(body.entity_type):
        from entity_normalization import ALLOWED_ENTITY_TYPES
        raise HTTPException(
            422,
            f"entity_type '{body.entity_type}' not in allowlist: {sorted(ALLOWED_ENTITY_TYPES)}"
        )

    sets: list[str] = []
    params: list = []
    idx = 1
    if body.name is not None:
        sets.append(f"name = ${idx}")
        params.append(body.name)
        idx += 1
        # Recompute name_normalized cuando cambia name (coord).
        sets.append(f"name_normalized = ${idx}")
        params.append(normalize_name(body.name))
        idx += 1
    if body.entity_type is not None:
        sets.append(f"entity_type = ${idx}")
        params.append(body.entity_type)
        idx += 1
    if body.notes is not None:
        sets.append(f"notes = ${idx}")
        params.append(body.notes)
        idx += 1
    sets.append(f"updated_at = now()")
    params.append(entry_id)

    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                f"UPDATE entity_dictionary SET {', '.join(sets)} WHERE id = ${idx} RETURNING *",
                *params,
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "name_normalized already exists for another entry")
        if row is None:
            raise HTTPException(404, "entry not found")
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'update_entity_dict', 'entity_dictionary', $2, $3::jsonb, $4)""",
            int(actor["sub"]), str(entry_id),
            json.dumps({"fields_updated": [s.split(" = ")[0] for s in sets]}),
            actor.get("organization_id"),
        )
    return _row_to_dict_entry(row)


@router.delete("/entity-dictionary/{entry_id}", status_code=204)
async def delete_dictionary_entry(
    entry_id: int,
    actor: dict = Depends(require_super),
) -> None:
    """Elimina entrada. Idempotente — 204 incluso si no existia."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM entity_dictionary WHERE id = $1", entry_id)
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'delete_entity_dict', 'entity_dictionary', $2, NULL, $3)""",
            int(actor["sub"]), str(entry_id), actor.get("organization_id"),
        )


# ---------------------------------------------------------------------------
# Task 4.5 — Stop entities CRUD (super-only, L2-4)
# ---------------------------------------------------------------------------

class StopEntityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200, pattern=r"^[\w\sÀ-ɏ.\-]+$")
    reason: Optional[str] = Field(None, max_length=500)


class StopEntityRow(BaseModel):
    id: int
    name: str
    name_normalized: str
    reason: Optional[str] = None
    created_by: Optional[int] = None
    created_at: str


def _row_to_stop_entity(row) -> StopEntityRow:
    return StopEntityRow(
        id=row["id"],
        name=row["name"],
        name_normalized=row["name_normalized"],
        reason=row["reason"],
        created_by=row["created_by"],
        created_at=row["created_at"].isoformat(),
    )


@router.post("/stop-entities", response_model=StopEntityRow, status_code=201)
async def create_stop_entity(
    body: StopEntityCreate,
    actor: dict = Depends(require_super),
) -> StopEntityRow:
    """Add entity to stop list. Super-only."""
    name_normalized = normalize_name(body.name)
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO stop_entities (name, name_normalized, reason, created_by)
                VALUES ($1, $2, $3, $4)
                RETURNING *
                """,
                body.name, name_normalized, body.reason, int(actor["sub"]),
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, f"stop entity '{name_normalized}' already exists")
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'create_stop_entity', 'stop_entities', $2, $3::jsonb, $4)""",
            int(actor["sub"]), str(row["id"]),
            json.dumps({"name": body.name, "reason": body.reason}),
            actor.get("organization_id"),
        )
    return _row_to_stop_entity(row)


@router.get("/stop-entities", response_model=list[StopEntityRow])
async def list_stop_entities(
    actor: dict = Depends(require_super),
) -> list[StopEntityRow]:
    """List all stop entities. Super-only."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM stop_entities ORDER BY name_normalized")
    return [_row_to_stop_entity(r) for r in rows]


@router.delete("/stop-entities/{stop_id}", status_code=204)
async def delete_stop_entity(
    stop_id: int,
    actor: dict = Depends(require_super),
) -> None:
    """Delete stop entity by id. Idempotent. Super-only."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM stop_entities WHERE id = $1", stop_id)
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'delete_stop_entity', 'stop_entities', $2, NULL, $3)""",
            int(actor["sub"]), str(stop_id), actor.get("organization_id"),
        )


@router.get("/stop-entities/check")
async def check_stop_entity(
    name: str,
    actor: dict = Depends(require_super),
) -> dict:
    """Check if name is in stop list. Super-only."""
    name_normalized = normalize_name(name)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name FROM stop_entities WHERE name_normalized = $1",
            name_normalized,
        )
    return {"name": name, "name_normalized": name_normalized, "is_stop": row is not None}


# ---------------------------------------------------------------------------
# Task 5.9 — Alias candidates review (super-only)
# ---------------------------------------------------------------------------

class AliasCandidateRow(BaseModel):
    id: int
    source_name: str
    target_node_id: int
    target_node_name: Optional[str] = None
    confidence: float
    occurrences: int
    status: str
    first_seen: str
    last_seen: str
    sample_contexts: Optional[list[str]] = None


class AliasCandidateReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["approved", "rejected"]
    merge: bool = Field(False, description="If approved and true, trigger entity merge.")
    reverse: bool = Field(False, description="If true, merge target INTO source instead of source into target.")
    reason: Optional[str] = Field(None, max_length=500)


@router.get("/alias-candidates", response_model=list[AliasCandidateRow])
async def list_alias_candidates(
    status: str = "pending",
    limit: int = Query(50, ge=1, le=200),
    actor: dict = Depends(get_current_user),
) -> list[AliasCandidateRow]:
    """List entity alias candidates. Defaults to pending. Super or CEO (own org)."""
    allowed = {"pending", "approved", "rejected", "archived"}
    if status not in allowed:
        raise HTTPException(400, f"status must be one of {sorted(allowed)}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _check_admin_op(conn, actor, "alias_candidates")
        if actor.get("is_super"):
            rows = await conn.fetch(
                """
                SELECT eac.id, eac.source_name, eac.target_node_id, n.name AS target_node_name,
                       eac.confidence, eac.occurrences, eac.status,
                       eac.first_seen, eac.last_seen, eac.sample_contexts
                FROM entity_alias_candidates eac
                JOIN nodes n ON n.id = eac.target_node_id
                WHERE eac.status = $1
                ORDER BY eac.occurrences DESC, eac.confidence DESC
                LIMIT $2
                """,
                status, limit,
            )
        else:
            actor_org = actor.get("organization_id")
            rows = await conn.fetch(
                """
                SELECT DISTINCT eac.id, eac.source_name, eac.target_node_id, n.name AS target_node_name,
                       eac.confidence, eac.occurrences, eac.status,
                       eac.first_seen, eac.last_seen, eac.sample_contexts
                FROM entity_alias_candidates eac
                JOIN nodes n ON n.id = eac.target_node_id
                JOIN nodes nn ON lower(nn.name) = lower(eac.source_name)
                JOIN claim_entity_links cel ON cel.entity_node_id = nn.id
                JOIN claims m ON m.id = cel.claim_id
                JOIN projects p ON p.id = m.project_id
                JOIN workspaces w ON w.id = p.workspace_id
                WHERE eac.status = $1 AND w.organization_id = $2
                ORDER BY eac.occurrences DESC, eac.confidence DESC
                LIMIT $3
                """,
                status, actor_org, limit,
            )
    return [
        AliasCandidateRow(
            id=r["id"],
            source_name=r["source_name"],
            target_node_id=r["target_node_id"],
            target_node_name=r["target_node_name"],
            confidence=float(r["confidence"]),
            occurrences=r["occurrences"],
            status=r["status"],
            first_seen=r["first_seen"].isoformat(),
            last_seen=r["last_seen"].isoformat(),
            sample_contexts=list(r["sample_contexts"]) if r["sample_contexts"] else None,
        )
        for r in rows
    ]


class AliasScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: float = Field(0.65, ge=0.0, le=1.0, description="pg_trgm similarity threshold")
    max_per_name: int = Field(3, ge=1, le=10, description="Max candidates per source name")
    name_filter: str | None = Field(None, min_length=1, max_length=256, description="Optional ILIKE filter on node names")
    dry_run: bool = Field(False, description="If true, preview without inserting")


class AliasScanResponse(BaseModel):
    found: int
    inserted: int
    updated: int
    total_pending: int
    candidates: list[dict] | None = None


@router.post("/alias-candidates/scan", response_model=AliasScanResponse)
async def scan_alias_candidates(
    body: AliasScanRequest,
    actor: dict = Depends(get_current_user),
) -> AliasScanResponse:
    """Scan all active nodes for alias candidates. Super or CEO (own org)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _check_admin_op(conn, actor, "alias_candidates")
    from gliner_service import scan_all_alias_candidates
    result = await scan_all_alias_candidates(
        pool,
        threshold=body.threshold,
        max_per_name=body.max_per_name,
        name_filter=body.name_filter,
        dry_run=body.dry_run,
    )
    return AliasScanResponse(**result)


@router.put("/alias-candidates/{candidate_id}", response_model=AliasCandidateRow)
async def review_alias_candidate(
    candidate_id: int,
    body: AliasCandidateReview,
    actor: dict = Depends(get_current_user),
) -> AliasCandidateRow:
    """Review an alias candidate (approve/reject). If approved + merge=true, merges entities."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT eac.*, n.name AS target_node_name
               FROM entity_alias_candidates eac
               JOIN nodes n ON n.id = eac.target_node_id
               WHERE eac.id = $1""",
            candidate_id,
        )
        if row is None:
            raise HTTPException(404, "not found")
        try:
            await _check_admin_op(conn, actor, "alias_candidates", row["source_name"])
        except HTTPException:
            raise HTTPException(404, "not found")
        if row["status"] != "pending":
            raise HTTPException(409, f"candidate already reviewed (status={row['status']})")

        await conn.execute(
            """UPDATE entity_alias_candidates
               SET status = $1, reviewed_by = $2, last_seen = now()
               WHERE id = $3""",
            body.status, int(actor["sub"]), candidate_id,
        )

        if body.status == "approved" and body.merge:
            source_node = await conn.fetchrow(
                "SELECT id FROM nodes WHERE lower(name) = lower($1) AND status = 'active' LIMIT 1",
                row["source_name"],
            )
            if source_node is None:
                raise HTTPException(422, f"source node '{row['source_name']}' not found as active node — merge skipped")

            target_name = await conn.fetchval(
                "SELECT name FROM nodes WHERE id = $1", row["target_node_id"]
            )
            if target_name:
                await _check_admin_op(conn, actor, "merge_entities", target_name)

            from graph import merge_entities as _merge_entities
            try:
                if body.reverse:
                    await _merge_entities(
                        row["target_node_id"], source_node["id"],
                        int(actor["sub"]), body.reason, pool,
                    )
                else:
                    await _merge_entities(
                        source_node["id"], row["target_node_id"],
                        int(actor["sub"]), body.reason, pool,
                    )
            except ValueError as exc:
                raise HTTPException(422, str(exc))
            audit_source = row["source_name"]
            audit_target = target_name
            if body.reverse:
                audit_source, audit_target = audit_target, audit_source
            await conn.execute(
                """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                VALUES ($1, 'merge_via_alias_review', 'entity', $2, $3::jsonb, $4)""",
                int(actor["sub"]), str(candidate_id),
                json.dumps({"source": audit_source, "target": audit_target, "candidate_id": candidate_id, "reverse": body.reverse}),
                actor.get("organization_id"),
            )

    # Fetch updated row
    async with pool.acquire() as conn:
        updated = await conn.fetchrow(
            """SELECT eac.*, n.name AS target_node_name
               FROM entity_alias_candidates eac
               JOIN nodes n ON n.id = eac.target_node_id
               WHERE eac.id = $1""",
            candidate_id,
        )
    return AliasCandidateRow(
        id=updated["id"],
        source_name=updated["source_name"],
        target_node_id=updated["target_node_id"],
        target_node_name=updated["target_node_name"],
        confidence=float(updated["confidence"]),
        occurrences=updated["occurrences"],
        status=updated["status"],
        first_seen=updated["first_seen"].isoformat(),
        last_seen=updated["last_seen"].isoformat(),
        sample_contexts=list(updated["sample_contexts"]) if updated["sample_contexts"] else None,
    )


# ---------------------------------------------------------------------------
# Task 5.10 — Merge entities (super-only)
# ---------------------------------------------------------------------------

class MergeEntitiesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_node_id: int = Field(..., gt=0, description="Node to merge (will be marked merged).")
    target_node_id: int = Field(..., gt=0, description="Canonical target node.")
    reason: Optional[str] = Field(None, max_length=500)
    keep_as_alias: bool = Field(False, description="Create approved alias source→target after merge")


@router.post("/merge-entities")
async def merge_entities_endpoint(
    body: MergeEntitiesRequest,
    actor: dict = Depends(get_current_user),
) -> dict:
    """Soft-merge source entity into target.

    Resolves target to canonical via chain compression.
    Marks source as 'merged'. Logs to entity_merge_log.
    """
    if body.source_node_id == body.target_node_id:
        raise HTTPException(422, "source and target must be different")
    from graph import merge_entities as _merge_entities
    pool = await get_pool()
    async with pool.acquire() as conn:
        src_name = await conn.fetchval("SELECT name FROM nodes WHERE id = $1", body.source_node_id)
        tgt_name = await conn.fetchval("SELECT name FROM nodes WHERE id = $1", body.target_node_id)
        if not src_name or not tgt_name:
            raise HTTPException(422, "source or target node not found")
        await _check_admin_op(conn, actor, "merge_entities", src_name)
        await _check_admin_op(conn, actor, "merge_entities", tgt_name)
    try:
        result = await _merge_entities(
            body.source_node_id, body.target_node_id,
            int(actor["sub"]), body.reason, pool,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'merge_entities', 'node', $2, $3::jsonb, $4)""",
            int(actor["sub"]), str(result["merge_log_id"]),
            json.dumps({"source_node_id": body.source_node_id, "target_node_id": body.target_node_id, "reason": body.reason}),
            actor.get("organization_id"),
        )
        if body.keep_as_alias:
            try:
                await conn.execute("""
                    INSERT INTO entity_alias_candidates (source_name, target_node_id, confidence, occurrences, status)
                    VALUES ($1, $2, 1.0, 1, 'approved')
                    ON CONFLICT DO NOTHING
                """, src_name, body.target_node_id)
                result["alias_created"] = True
            except Exception:
                result["alias_created"] = False
    return result


# ---------------------------------------------------------------------------
# Task 5.11 — Undo merge (super-only)
# ---------------------------------------------------------------------------

class UndoMergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_node_id: int = Field(..., gt=0, description="Node to un-merge (reverts to active).")


@router.post("/undo-merge")
async def undo_merge_endpoint(
    body: UndoMergeRequest,
    actor: dict = Depends(get_current_user),
) -> dict:
    """Revert a merge operation.

    Restores source node to status='active'. One-time only — already-undone merges return 409.
    """
    from graph import undo_merge as _undo_merge
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _check_admin_op(conn, actor, "undo_merge")
        src_name = await conn.fetchval("SELECT name FROM nodes WHERE id = $1", body.source_node_id)
        if not src_name:
            raise HTTPException(404, "not found")
        try:
            await _check_admin_op(conn, actor, "undo_merge", src_name)
        except HTTPException:
            raise HTTPException(404, "not found")
    try:
        result = await _undo_merge(body.source_node_id, pool)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'undo_merge', 'node', $2, $3::jsonb, $4)""",
            int(actor["sub"]), str(result["merge_log_id"]),
            json.dumps({"source_node_id": body.source_node_id}),
            actor.get("organization_id"),
        )
    return result


# ---------------------------------------------------------------------------
# Task 5.14 — Trust tier management (super-only)
# ---------------------------------------------------------------------------

class TrustTierUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trust_tier: int = Field(..., ge=0, le=3, description="Trust tier 0-3 (0=untrusted, 3=gold).")


@router.put("/documents/{document_id}/trust-tier")
async def set_document_trust_tier(
    document_id: str,
    body: TrustTierUpdate,
    actor: dict = Depends(get_current_user),
) -> dict:
    """Set trust tier for a document (0=untrusted, 1=default, 2=verified, 3=gold)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _check_admin_op(conn, actor, "trust_tier")
        if not actor.get("is_super"):
            doc_org = await conn.fetchval(
                """SELECT w.organization_id FROM documents d
                JOIN projects p ON p.id = d.project_id
                JOIN workspaces w ON w.id = p.workspace_id
                WHERE d.id = $1 AND d.status != 'deleted'""",
                document_id,
            )
            if doc_org is None or doc_org != actor.get("organization_id"):
                raise HTTPException(404, "document not found")
        result = await conn.execute(
            "UPDATE documents SET trust_tier = $1 WHERE id = $2 AND status != 'deleted'",
            body.trust_tier, document_id,
        )
        if result == "UPDATE 0":
            raise HTTPException(404, "document not found")
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'set_trust_tier', 'document', $2, $3::jsonb, $4)""",
            int(actor["sub"]), document_id,
            json.dumps({"trust_tier": body.trust_tier}),
            actor.get("organization_id"),
        )
    return {"document_id": document_id, "trust_tier": body.trust_tier}


# ---------------------------------------------------------------------------
# Task 5.15 — Related documents confirm (super-only)
# ---------------------------------------------------------------------------

class ConfirmRelationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(..., description="UUID of source document.")
    target_id: str = Field(..., description="UUID of target document.")


@router.put("/related-documents/confirm")
async def confirm_related_document(
    body: ConfirmRelationRequest,
    actor: dict = Depends(get_current_user),
) -> dict:
    """Mark a related_documents entry as confirmed by the current user."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _check_admin_op(conn, actor, "confirm_related_docs")
        if not actor.get("is_super"):
            actor_org = actor.get("organization_id")
            for doc_label, doc_id in [("source", body.source_id), ("target", body.target_id)]:
                doc_org = await conn.fetchval(
                    """SELECT w.organization_id FROM documents d
                    JOIN projects p ON p.id = d.project_id
                    JOIN workspaces w ON w.id = p.workspace_id
                    WHERE d.id = $1 AND d.status != 'deleted'""",
                    doc_id,
                )
                if doc_org is None or doc_org != actor_org:
                    raise HTTPException(404, f"{doc_label} document not found")
        result = await conn.execute(
            "UPDATE related_documents SET confirmed_by = $1 WHERE source_id = $2 AND target_id = $3",
            int(actor["sub"]), body.source_id, body.target_id,
        )
        if result == "UPDATE 0":
            raise HTTPException(404, "relation not found")
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'confirm_related_docs', 'related_documents', $2, $3::jsonb, $4)""",
            int(actor["sub"]), body.source_id,
            json.dumps({"source_id": body.source_id, "target_id": body.target_id}),
            actor.get("organization_id"),
        )
    return {"source_id": body.source_id, "target_id": body.target_id, "confirmed": True}


@router.get("/graph-vocabulary", status_code=200)
async def get_graph_vocabulary(
    actor: dict = Depends(get_current_user),
) -> dict:
    """Vocabulario del grafo: entidades del diccionario + predicados aprobados.

    Formato minimalista para que un LLM genere tripletas gobernadas.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _check_admin_op(conn, actor, "graph_vocabulary")
        entities = await conn.fetch(
            "SELECT name, entity_type FROM entity_dictionary ORDER BY entity_type, name"
        )
        predicates = await conn.fetch(
            "SELECT name, COALESCE(description, '') AS description, state, cluster FROM predicates_canonical WHERE state = 'approved' ORDER BY cluster, name"
        )
    return {
        "entities": [{"name": r["name"], "type": r["entity_type"]} for r in entities],
        "predicates": [{"name": r["name"], "description": r["description"], "state": r["state"], "cluster": r["cluster"]} for r in predicates],
        "entity_count": len(entities),
        "predicate_count": len(predicates),
    }


# ---------------------------------------------------------------------------
# Predicates CRUD (dashboard #44)
# ---------------------------------------------------------------------------

class PredicateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field("")
    cluster: str = Field("general")
    state: str = Field("approved", pattern="^(experimental|candidate|approved|deprecated|archived|forbidden)$")


class PredicateUpdate(BaseModel):
    description: Optional[str] = None
    cluster: Optional[str] = None
    state: Optional[str] = Field(None, pattern="^(experimental|candidate|approved|deprecated|archived|forbidden)$")


class PredicateResponse(BaseModel):
    name: str
    description: str
    cluster: str
    state: str
    domain: Optional[str] = None
    symmetric: bool
    transitive: bool
    created_at: Optional[datetime] = None


@router.post("/predicates", response_model=PredicateResponse, status_code=201)
async def create_predicate(
    body: PredicateCreate,
    actor: dict = Depends(require_super),
) -> PredicateResponse:
    """Create a new canonical predicate. Super-only."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow("""
                INSERT INTO predicates_canonical (name, description, cluster, state, ontology_layer)
                VALUES ($1, $2, $3, $4, 'domain')
                RETURNING name, description, cluster, state, domain, "symmetric", "transitive", created_at
            """, body.name, body.description, body.cluster, body.state)
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, f"predicate '{body.name}' already exists")
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'create_predicate', 'predicates_canonical', $2, $3::jsonb, $4)""",
            int(actor["sub"]), body.name,
            json.dumps({"description": body.description, "cluster": body.cluster, "state": body.state}),
            actor.get("organization_id"),
        )
    return PredicateResponse(**dict(row))


@router.put("/predicates/{name}", response_model=PredicateResponse)
async def update_predicate(
    name: str,
    body: PredicateUpdate,
    actor: dict = Depends(require_super),
) -> PredicateResponse:
    """Update predicate metadata. Super-only."""
    sets = []
    params: list = [name]
    i = 2
    if body.description is not None:
        sets.append(f"description = ${i}"); params.append(body.description); i += 1
    if body.cluster is not None:
        sets.append(f"cluster = ${i}"); params.append(body.cluster); i += 1
    if body.state is not None:
        sets.append(f"state = ${i}"); params.append(body.state); i += 1
        if body.state in ("deprecated", "archived", "forbidden"):
            sets.append("deprecated_since = now()")
    if not sets:
        raise HTTPException(400, "no fields to update")
    sets.append("updated_at = now()")

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""UPDATE predicates_canonical SET {', '.join(sets)}
            WHERE name = $1
            RETURNING name, description, cluster, state, domain, "symmetric", "transitive", created_at""",
            *params,
        )
        if row is None:
            raise HTTPException(404, "predicate not found")
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'update_predicate', 'predicates_canonical', $2, $3::jsonb, $4)""",
            int(actor["sub"]), name,
            json.dumps({"fields_updated": [s.split(" = ")[0] for s in sets if " = " in s]}),
            actor.get("organization_id"),
        )
    return PredicateResponse(**dict(row))


@router.delete("/predicates/{name}", status_code=204)
async def delete_predicate(
    name: str,
    actor: dict = Depends(require_super),
) -> None:
    """Delete a canonical predicate. Super-only. Idempotent."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM predicates_canonical WHERE name = $1", name)
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'delete_predicate', 'predicates_canonical', $2, NULL, $3)""",
            int(actor["sub"]), name, actor.get("organization_id"),
        )


@router.post("/entity-dictionary/reload", status_code=200)
async def reload_dictionary_cache(
    actor: dict = Depends(require_super),
) -> dict:
    """Recarga el cache RAM del diccionario desde BD. Super-only.

    Invalidacion explicita post-CRUD. El cache se carga tambien al arranque
    uvicorn (lifespan FastAPI), pero CRUD no auto-invalida — hay que llamar
    este endpoint despues de POST/PUT/DELETE para que los cambios apliquen
    al pipeline GLiNER (decision adv-code 2026-05-09: cache RAM al arranque
    + endpoint reload super-only).
    """
    pool = await get_pool()
    count = await load_dictionary_to_cache(pool)
    return {"reloaded": True, "entries": count}
