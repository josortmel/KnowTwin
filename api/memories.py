"""Endpoints de memorias — .2.

Endpoints:
- POST /memories            crear memoria con embedding automático y GLiNER entity linking.
- GET  /memories/{id}       leer memoria con check de permisos.
- PUT  /memories/{id}       actualizar memoria (re-embed si content cambia).
- DELETE /memories/{id}     soft delete a tabla `trash`.
- GET  /memories/recent     listado filtrado por permisos + visibility.

Modelo de permisos (cascada CEO/Lead/Worker del plan v3 §4.2 + visibility):
- Super: ve y modifica todo.
- CEO: ve y modifica memorias de su organization (workspaces de su org).
- Lead de workspace W: ve memorias de workspaces W. Modifica las que él creó
  + las de cualquier project de W.
- Member de project P: ve memorias de P. Modifica solo las que él creó.
- Visibility=private: solo visible para user_id creador + super + CEO de la org.

.
- POST /memories: tras INSERT, llama al servicio embeddings (POST /embed/text con
  prompt_name=passage) y hace UPDATE con vector(512). Todo en una transaccion —
  si embeddings falla, se hace rollback del INSERT (decision A: invariante
  "memoria sin embedding es invisible" prevalece sobre disponibilidad parcial).
- PUT /memories/{id}: re-embed solo si content cambia. Otros campos
  (tags/visibility/type/media_path) NO disparan re-embed.

Entity linking (memory_entity_links) activo via GLiNER multilingual desde Fase 3.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from asyncpg.exceptions import ForeignKeyViolationError
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from auth import get_current_user
from db import get_pool
from embeddings_client import embed_text
from permissions import (
    can_write_memory,
    no_null_bytes as _no_null_bytes,
    visible_project_ids,
    visible_workspace_ids,
)
from settings import ENABLE_AUTO_LINK, ENABLE_POST_HOC_CLASSIFIER


# Limites de tamaño (VS1 adv-seg L1 — DoS prevention) y validacion de null bytes
# (VS3 adv-seg L1 — soft-delete unbreakable). Aplicados a TEXT y TEXT[].
# DEBT-TA5 verificador L2: aunque embeddings acepta hasta 32k, encodear ese
# tamaño tarda ~30s en la 2080 Ti — justo en el timeout HTTP. Bajamos a 16k
# para garantizar margen funcional. Documentos largos van por Fase 4 (Docling
# + chunking), no entran como memoria literal.
MAX_CONTENT_LEN = 16_000      # ~16KB, margen funcional sobre la GPU disponible
MAX_TAGS = 50                 # max numero de tags por memoria
MAX_TAG_LEN = 200             # max chars por tag individual
MAX_MEDIA_PATH_LEN = 1_024


# ---------------------------------------------------------------------------
# Constantes de embedding — # ---------------------------------------------------------------------------

# Tag del modelo persistido en `memories.embedding_model`. Si el modelo cambia
# en el futuro (Fase 7 escala), este tag se actualiza para distinguir vectores
# de versiones distintas en queries de mantenimiento. La logica HTTP del cliente
# de embeddings vive en embeddings_client.py (refactor deuda #23, 2026-05-08).
EMBEDDING_MODEL_TAG = "jina-v4"


router = APIRouter(prefix="/memories", tags=["memories"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

# OBS-2 (verificador L1): Literal explícitos para validacion 422 desde Pydantic
# ANTES de tocar DB. Coincide con los ENUMs del schema §1.5.
MemoryType = Literal["momento", "decision", "acuerdo", "tecnico", "descubrimiento", "observacion", "referencia", "caso", "skill"]
ContentModality = Literal["text", "image", "audio", "document", "video"]
Visibility = Literal["public", "private"]


class MemoryCreate(BaseModel):
    # Deuda #22: rechazar campos desconocidos. Cliente que envia `agent_id`
    # legacy (numerico, formato pre-2026-05-08) recibe 422 explicito, no 201
    # silencioso con su memoria sin agente.
    model_config = ConfigDict(extra="forbid")

    type: MemoryType = Field(..., description="Uno de: momento, decision, acuerdo, tecnico, descubrimiento, observacion, referencia, caso, skill")
    content: str = Field(..., min_length=1, max_length=MAX_CONTENT_LEN, description="Texto de la memoria")
    workspace_id: int
    project_id: int
    agent_identifier: Optional[str] = Field(None, min_length=1, max_length=128, description="Agent identifier. Must match a registered agent name.")
    content_type: ContentModality = "text"
    visibility: Visibility = "public"
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    media_path: Optional[str] = Field(None, max_length=MAX_MEDIA_PATH_LEN)
    image_base64: Optional[str] = Field(
        None,
        max_length=10_000_000,
        description="Imagen en base64 (PNG/JPEG/WebP). Si presente, se embede en memory_embeddings con modality='image'. Content sigue required como descripción textual.",
    )
    source_document_id: Optional[UUID] = Field(
        None,
        description="UUID del documento fuente (Task 4.9). Si presente, se inserta en memory_document_links.",
    )
    foresight_start: Optional[datetime] = None
    foresight_end: Optional[datetime] = None
    metadata: Optional[dict] = None

    @field_validator("content")
    @classmethod
    def _validate_content(cls, v: str) -> str:
        return _no_null_bytes(v, "content")

    @field_validator("agent_identifier")
    @classmethod
    def _validate_agent_identifier(cls, v: Optional[str]) -> Optional[str]:
        # NV_IDENT_NULL fix Deuda #22 (adv-seg Loop 1): consistencia con
        # content/tags/media_path. null bytes en identifier llegarian al lookup
        # SQL y siempre devolverian 422 — el check explicito mantiene el patron.
        return _no_null_bytes(v, "agent_identifier") if v is not None else v

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, v: list[str]) -> list[str]:
        for t in v:
            if len(t) > MAX_TAG_LEN:
                raise ValueError(f"tag exceeds max length {MAX_TAG_LEN}")
            _no_null_bytes(t, "tag")
        return v

    @field_validator("media_path")
    @classmethod
    def _validate_media_path(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _no_null_bytes(v, "media_path")

    @field_validator("foresight_end")
    @classmethod
    def _v_foresight(cls, v, info):
        if v is not None:
            fs = info.data.get("foresight_start")
            if fs is None:
                raise ValueError("foresight_end requires foresight_start")
            if v <= fs:
                raise ValueError("foresight_end must be after foresight_start")
            from datetime import timedelta
            if v - fs > timedelta(days=730):
                raise ValueError("foresight window cannot exceed 2 years")
        return v

    @field_validator("metadata")
    @classmethod
    def _v_metadata(cls, v, info):
        mem_type = info.data.get("type")
        if v is None:
            if mem_type == "caso":
                raise ValueError("caso requires metadata with task_type and success")
            if mem_type == "skill":
                raise ValueError("skill requires metadata with task_signature and steps")
            return v
        def _has_null(obj):
            if isinstance(obj, str):
                return "\x00" in obj
            if isinstance(obj, dict):
                return any(_has_null(k) or _has_null(vv) for k, vv in obj.items())
            if isinstance(obj, (list, tuple)):
                return any(_has_null(item) for item in obj)
            return False
        if _has_null(v):
            raise ValueError("metadata contains null bytes")
        raw = json.dumps(v)
        if len(raw.encode("utf-8")) > 65536:
            raise ValueError("metadata exceeds 64KB")
        mem_type = info.data.get("type")
        if mem_type == "caso":
            if "task_type" not in v:
                raise ValueError("caso requires metadata.task_type")
            if "success" not in v:
                raise ValueError("caso requires metadata.success")
        elif mem_type == "skill":
            if "task_signature" not in v:
                raise ValueError("skill requires metadata.task_signature")
            if "steps" not in v or not isinstance(v["steps"], list):
                raise ValueError("skill requires metadata.steps (list)")
        return v


class MemoryUpdate(BaseModel):
    content: Optional[str] = Field(None, min_length=1, max_length=MAX_CONTENT_LEN)
    type: Optional[MemoryType] = None
    visibility: Optional[Visibility] = None
    tags: Optional[list[str]] = Field(None, max_length=MAX_TAGS)
    media_path: Optional[str] = Field(None, max_length=MAX_MEDIA_PATH_LEN)
    metadata: Optional[dict] = None

    @field_validator("content")
    @classmethod
    def _v_content(cls, v: Optional[str]) -> Optional[str]:
        return _no_null_bytes(v, "content") if v is not None else v

    @field_validator("tags")
    @classmethod
    def _v_tags(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        for t in v:
            if len(t) > MAX_TAG_LEN:
                raise ValueError(f"tag exceeds max length {MAX_TAG_LEN}")
            _no_null_bytes(t, "tag")
        return v

    @field_validator("media_path")
    @classmethod
    def _v_media_path(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _no_null_bytes(v, "media_path")

    @field_validator("metadata")
    @classmethod
    def _v_metadata(cls, v):
        if v is None:
            return v
        def _has_null(obj):
            if isinstance(obj, str):
                return "\x00" in obj
            if isinstance(obj, dict):
                return any(_has_null(k) or _has_null(vv) for k, vv in obj.items())
            if isinstance(obj, (list, tuple)):
                return any(_has_null(item) for item in obj)
            return False
        if _has_null(v):
            raise ValueError("null bytes in metadata")
        raw = json.dumps(v)
        if len(raw.encode()) > 65536:
            raise ValueError("metadata > 64KB")
        return v


class MemoryResponse(BaseModel):
    id: UUID
    user_id: Optional[int]
    agent_identifier: Optional[str]
    workspace_id: int
    project_id: int
    type: str
    content_type: str
    visibility: str
    content: str
    tags: list[str]
    weight: float
    weight_base: float
    access_count: int
    media_path: Optional[str]
    created_at: datetime
    updated_at: datetime
    last_accessed: Optional[datetime]
    summary: Optional[str] = None
    staleness: Optional[str] = None
    foresight_start: Optional[datetime] = None
    foresight_end: Optional[datetime] = None
    metadata: Optional[dict] = None


class MemoryListResponse(BaseModel):
    items: list[MemoryResponse]
    total: int
    limit: int
    cursor_next: Optional[str]


# ---------------------------------------------------------------------------
# Permisos: helpers `visible_workspace_ids`, `can_read_memory`, `can_write_memory`
# extraídos a permissions.py en .
# Importados al top del archivo. Comportamiento idéntico al previo.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=MemoryResponse, status_code=201)
async def create_memory(
    body: MemoryCreate,
    actor: dict = Depends(get_current_user),
) -> MemoryResponse:
    """Crear memoria con embedding automatico.

    VS2 fix 
    30s timeout) se hace FUERA de pool.acquire() para evitar starvation del
    pool asyncpg. Flujo: validaciones rapidas → libero pool → embed (sin DB)
    → re-acquire pool → INSERT atomico con embedding ya en la fila. Asi solo
    se retiene la conexion para queries rapidas.
    """
    pool = await get_pool()

    # FASE 1 — validaciones + permisos (pool.acquire rapido, sin embed)
    async with pool.acquire() as conn:
        # BC1 fix (adv-code): la query previa con fetchval `if ws_org is False`
        # era dead code (asyncpg.fetchval devuelve None, no False, cuando no
        # hay row). El check correcto es el `if ws is None` de abajo.
        ws = await conn.fetchrow(
            "SELECT organization_id FROM workspaces WHERE id = $1", body.workspace_id
        )
        if ws is None:
            raise HTTPException(404, "workspace not found")
        proj = await conn.fetchrow(
            "SELECT workspace_id FROM projects WHERE id = $1", body.project_id
        )
        if proj is None:
            raise HTTPException(404, "project not found")
        if proj["workspace_id"] != body.workspace_id:
            raise HTTPException(400, "project does not belong to workspace")

        # Permisos para escribir en este workspace.
        # OBS-1 (verificador L1): mensaje de error diferenciado para Lead que
        # intenta tocar workspace ajeno vs Worker sin membership en el project.
        if not actor.get("is_super"):
            if actor.get("is_ceo"):
                if actor.get("organization_id") != ws["organization_id"]:
                    raise HTTPException(403, "ceo cannot write in workspace of another organization")
            else:
                lead_ws = actor.get("lead_workspaces") or []
                if lead_ws and body.workspace_id not in lead_ws:
                    raise HTTPException(403, "user is lead of other workspaces but not this one")
                if body.workspace_id not in lead_ws:
                    is_member = await conn.fetchval(
                        "SELECT 1 FROM project_members WHERE user_id=$1 AND project_id=$2",
                        int(actor["sub"]), body.project_id,
                    )
                    if not is_member:
                        raise HTTPException(403, "user is not member of the target project")

        # weight desde memory_type_config
        weight_row = await conn.fetchrow(
            "SELECT base_weight FROM memory_type_config WHERE type = $1", body.type
        )
        if weight_row is None:
            raise HTTPException(422, f"unknown memory type: {body.type}")
        weight_base = float(weight_row["base_weight"])

        # Ownership check (DEBT-13): resolve agent + verify ownership before INSERT.
        actor_id = int(actor["sub"])
        is_super = bool(actor.get("is_super"))
        resolved_agent_id: Optional[int] = None
        if body.agent_identifier:
            agent_row = await conn.fetchrow(
                "SELECT id, user_id FROM agents WHERE identifier = $1 AND active = true",
                body.agent_identifier)
            if agent_row is None:
                raise HTTPException(422, f"agent '{body.agent_identifier}' not found")
            if not is_super:
                if agent_row["user_id"] is None:
                    raise HTTPException(403, "cannot create memory for system agent")
                if int(agent_row["user_id"]) != actor_id:
                    raise HTTPException(403, "cannot create memory for agent owned by another user")
            resolved_agent_id = agent_row["id"]
    # Pool liberado aqui — la conexion vuelve al pool para otros endpoints.

    # FASE 2 — embed FUERA del pool. Si falla, lanzamos 503 sin tocar DB.
    # . Imagen si presente.
    import time as _time
    import logging as _logging
    _perf_log = _logging.getLogger("ecodb.perf")
    _t0 = _time.time()

    embedding_literal = await embed_text(body.content, prompt_name="passage")

    image_embedding_literal: Optional[str] = None
    if body.image_base64 is not None:
        from embeddings_client import embed_image
        image_embedding_literal = await embed_image(body.image_base64)

    _t_embed = _time.time()
    _perf_log.info("create_memory phase=embed %.2fs", _t_embed - _t0)

    # FASE 3 — INSERT atomico con embedding en la misma query. Sin transaction
    # explicita necesaria: una sola sentencia es atomica por defecto.
    # Deuda #23 fix: parametros distintos para weight ($10) y weight_base ($11),
    # ambos con mismo valor pero indices separados — antes era $10,$10 que
    # funciona pero confunde al lector (parece typo) y rompe si alguien
    # añade params sin recontar.
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                WITH inserted AS (
                  INSERT INTO memories
                    (user_id, agent_id, workspace_id, project_id, type, content_type,
                     visibility, content, tags, weight, weight_base, media_path,
                     embedding, embedding_model,
                     foresight_start, foresight_end, metadata)
                  VALUES ($1, $2, $3, $4, $5::memory_type, $6::content_modality,
                          $7::visibility, $8, $9, $10, $11, $12,
                          $13::vector, $14,
                          $15, $16, $17::jsonb)
                  RETURNING *
                )
                SELECT i.*, a.identifier AS agent_identifier
                FROM inserted i
                LEFT JOIN agents a ON a.id = i.agent_id
                """,
                int(actor["sub"]), resolved_agent_id, body.workspace_id, body.project_id,
                body.type, body.content_type, body.visibility, body.content,
                body.tags, weight_base, weight_base, body.media_path,
                embedding_literal, EMBEDDING_MODEL_TAG,
                body.foresight_start, body.foresight_end,
                json.dumps(body.metadata or {}),
            )
        except ForeignKeyViolationError:
            # NV1-10 cierre Deuda #22 (2026-05-08): TOCTOU FASE1→FASE3. Si
            # workspace/project/user/agent fue borrado entre validacion y INSERT
            # (~30s gap por embed), Postgres lanza FK violation. Mapeamos a 422
            # claro en lugar de 5xx confuso. Sin reservar fila ni cambiar
            # invariante "memoria sin embedding no existe".
            raise HTTPException(
                422,
                "referenced resource (workspace, project, user or agent) was deleted concurrently",
            )

        # FASE 3b — .
        # Backward compat: memories.embedding sigue lleno con text embedding (arriba).
        # memory_embeddings es la fuente de verdad para search post-migración.
        try:
            await conn.execute(
                """
                INSERT INTO memory_embeddings (memory_id, modality, embedding, source_ref)
                VALUES ($1, 'text', $2::vector, NULL)
                ON CONFLICT (memory_id, modality) DO NOTHING
                """,
                row["id"], embedding_literal,
            )
            if image_embedding_literal is not None:
                await conn.execute(
                    """
                    INSERT INTO memory_embeddings (memory_id, modality, embedding, source_ref)
                    VALUES ($1, 'image', $2::vector, $3)
                    ON CONFLICT (memory_id, modality) DO NOTHING
                    """,
                    row["id"], image_embedding_literal, body.media_path,
                )
        except Exception as _me_exc:
            _logging.getLogger("ecodb.memory_embeddings").warning(
                "FASE 3b memory_embeddings insert failed for memory=%s: %r",
                str(row["id"]), _me_exc,
            )

        # SSE broadcast BEFORE GLiNER (memory already committed, no delay)
        from events import broadcast_event, resolve_org_id_from_project
        _broadcast_org = await resolve_org_id_from_project(conn, body.project_id)
        if _broadcast_org is None:
            _broadcast_org = actor.get("organization_id")
        await broadcast_event("memory_created", {
            "memory_id": str(row["id"]),
            "type": body.type,
            "agent_identifier": body.agent_identifier or "",
        }, org_id=_broadcast_org)

        _t_insert = _time.time()
        _perf_log.info("create_memory phase=insert %.2fs", _t_insert - _t_embed)
    # conn released here — pool free during GLiNER CPU inference

    # FASE 4 — .
    # Decisión     # - Skip + log si GLiNER falla → NO rollback memoria. GLiNER es
    #   enriquecimiento, no la verdad de la memoria.
    # - Si AGE/SQL fallan dentro del linking → rollback de la transaction
    #   de linking (deja memoria sin links, no rompe la creación).
    # - Atomicidad: linking dentro de su propia conn.transaction(); la
    #   memoria YA está commiteada por el INSERT atomic single-statement
    #   anterior. La transaction de linking solo rollback los links, no
    #   la memoria.
    # Perf fix: GLiNER acquires own conn so first conn is freed before
    # CPU inference starts (prevents pool starvation under concurrency).
    from graph import link_entities_from_content
    _gliner_log = _logging.getLogger("ecodb.gliner_link")
    try:
        async with pool.acquire() as gliner_conn:
            async with gliner_conn.transaction():
                await link_entities_from_content(gliner_conn, row["id"], body.content, pool)
    except Exception as _gliner_exc:
        #         # logger.warning explícito en lugar de silencio total. Antes este
        # except suprimia errores de AGE/SQL (conexion caida, constraint
        # violation, timeout pool) sin rastro en logs. Memoria queda sin
        # entity_links — aceptable, pero los operadores deben saber que
        # ocurrio. Distinto de errores de GLiNER (esos los maneja
        # link_entities_from_content con su propio log BC2).
        _gliner_log.warning(
            "FASE 4 entity linking failed for memory=%s: %r",
            str(row["id"]), _gliner_exc,
        )

    _t_gliner = _time.time()
    _perf_log.info("create_memory phase=gliner %.2fs", _t_gliner - _t_insert)

    # FASE 4b — co-occurrence triples (best-effort)
    try:
        from graph import update_cooccurrence_triples
        async with pool.acquire() as cooc_conn:
            entity_ids = await cooc_conn.fetch(
                "SELECT entity_node_id FROM memory_entity_links WHERE memory_id = $1",
                row["id"],
            )
            if len(entity_ids) >= 2:
                async with cooc_conn.transaction():
                    await update_cooccurrence_triples(
                        cooc_conn,
                        [r["entity_node_id"] for r in entity_ids],
                    )
    except Exception as _cooc_exc:
        _logging.getLogger("ecodb.cooccurrence").warning(
            "Co-occurrence triples failed for memory=%s: %r", str(row["id"]), _cooc_exc,
        )

    _t_cooc = _time.time()
    _perf_log.info("create_memory phase=cooccurrence %.2fs", _t_cooc - _t_gliner)

    # FASE 5 — auto-tag, source document link, auto-link
    async with pool.acquire() as conn:
        # Task 5.18 — Auto-tag by extracted entities (best-effort)
        try:
            entity_rows = await conn.fetch(
                """SELECT n.name, n.type::text FROM memory_entity_links mel
                   JOIN nodes n ON n.id = mel.entity_node_id
                   WHERE mel.memory_id = $1
                     AND n.type IS NOT NULL AND n.type != 'unknown'
                   ORDER BY n.type, n.name LIMIT 10""",
                row["id"],
            )
            if entity_rows:
                auto_tags = [f"auto_tag:{r['type']}:{r['name'].lower().strip()}" for r in entity_rows]
                existing_tags = list(row["tags"]) if row.get("tags") else []
                all_tags = existing_tags + [t for t in auto_tags if t not in existing_tags]
                await conn.execute("UPDATE memories SET tags = $1 WHERE id = $2", all_tags, row["id"])
        except Exception as _at_exc:
            _logging.getLogger("ecodb.auto_tag").warning(
                "Auto-tag failed for memory=%s: %r", str(row["id"]), _at_exc
            )

        # Auto-tag case_candidate for tecnico/observacion with task_type+result in metadata
        if body.type in ('tecnico', 'observacion') and body.metadata:
            if 'task_type' in body.metadata and 'result' in body.metadata:
                try:
                    await conn.execute("""
                        UPDATE memories SET tags = array_append(tags, 'case_candidate')
                        WHERE id = $1 AND NOT ('case_candidate' = ANY(tags))
                    """, row["id"])
                except Exception as _cc_exc:
                    _logging.getLogger("ecodb.case_candidate").warning(
                        "case_candidate auto-tag failed for memory=%s: %r", str(row["id"]), _cc_exc)

        _t_autotag = _time.time()
        _perf_log.info("create_memory phase=auto_tag %.2fs", _t_autotag - _t_gliner)

        # B.5: post-hoc classifier Pass 1 (heuristic, sync — safe inside conn)
        _classification_tag: str | None = None
        if ENABLE_POST_HOC_CLASSIFIER:
            try:
                from classifier import classify_memory
                _cl_result = classify_memory(body.content, body.type)
                if _cl_result and _cl_result["confidence"] >= 0.5:
                    _classification_tag = f"classified:{_cl_result['template_type']}"
                    await conn.execute(
                        "UPDATE memories SET tags = array_append(tags, $1) WHERE id = $2 AND NOT ($1 = ANY(tags))",
                        _classification_tag, row["id"])
            except Exception as _cl_exc:
                _logging.getLogger("ecodb.classifier").warning("Classification Pass1 failed: %r", _cl_exc)

        # Task 4.9: link memory to source document (best-effort)
        if body.source_document_id is not None:
            try:
                await conn.execute(
                    """
                    INSERT INTO memory_document_links (memory_id, document_id)
                    VALUES ($1, $2)
                    ON CONFLICT DO NOTHING
                    """,
                    row["id"], body.source_document_id,
                )
            except Exception as _mdl_exc:
                _logging.getLogger("ecodb.memory_doc_link").warning(
                    "memory_document_links insert failed for memory=%s doc=%s: %r",
                    str(row["id"]), str(body.source_document_id), _mdl_exc,
                )

        # Task 5.7: Auto-link memoria↔documento
        if ENABLE_AUTO_LINK and row.get("embedding") is not None:
            _al_log = _logging.getLogger("ecodb.auto_link")
            try:
                auto_links = await conn.fetch("""
                    SELECT dc.document_id, d.status,
                           1 - (dc.embedding <=> $1::vector) AS cosine
                    FROM document_chunks dc
                    JOIN documents d ON d.id = dc.document_id
                    WHERE dc.embedding IS NOT NULL
                      AND d.status != 'deleted'
                      AND d.project_id = $2
                    ORDER BY dc.embedding <=> $1::vector
                    LIMIT 10
                """, row["embedding"], row["project_id"])

                linked = 0
                seen_docs = set()
                for al in auto_links:
                    if linked >= 3:
                        break
                    doc_id = al["document_id"]
                    if doc_id in seen_docs:
                        continue
                    cosine = float(al["cosine"])
                    if cosine < 0.78:
                        break
                    seen_docs.add(doc_id)
                    await conn.execute("""
                        INSERT INTO memory_document_links
                            (memory_id, document_id, link_type, confidence, validated)
                        VALUES ($1, $2, 'auto', $3, false)
                        ON CONFLICT (memory_id, document_id) DO NOTHING
                    """, row["id"], doc_id, cosine)
                    linked += 1

                if linked > 0:
                    _al_log.info("Auto-linked memory=%s to %d docs", str(row["id"]), linked)
            except Exception as _al_exc:
                _al_log.warning("Auto-link failed for memory=%s: %r", str(row["id"]), _al_exc)

    # B.5 Pass 2: LLM classifier OUTSIDE conn to avoid pool starvation during 30s call
    if ENABLE_POST_HOC_CLASSIFIER and _classification_tag is None:
        try:
            from classifier import classify_with_llm
            _cl2_result = await classify_with_llm(body.content)
            if _cl2_result and _cl2_result["confidence"] >= 0.5:
                _tag2 = f"classified:{_cl2_result['template_type']}"
                async with pool.acquire() as _conn2:
                    await _conn2.execute(
                        "UPDATE memories SET tags = array_append(tags, $1) WHERE id = $2 AND NOT ($1 = ANY(tags))",
                        _tag2, row["id"])
        except Exception as _cl2_exc:
            _logging.getLogger("ecodb.classifier").warning("Classification Pass2 failed: %r", _cl2_exc)

    _perf_log.info("create_memory TOTAL %.2fs", _time.time() - _t0)
    return _row_to_response(row)


@router.get("/recent", response_model=MemoryListResponse)
async def list_recent(
    limit: int = Query(20, ge=1, le=100),
    workspace_id: Optional[int] = Query(None, description="Filtrar a un workspace concreto. 403 si sin acceso (anti-IDOR)."),
    project_id: Optional[int] = Query(None, description="Filtrar a un project concreto. 403 si sin acceso (anti-IDOR)."),
    user_id_filter: Optional[int] = Query(None, alias="user_id", description="Filtrar por creador."),
    agent_identifier: Optional[str] = Query(None, min_length=1, max_length=128, description="Filtrar por agente."),
    fecha_desde: Optional[datetime] = Query(None, description="Memorias creadas >= esta fecha (."),
    fecha_hasta: Optional[datetime] = Query(None, description="Memorias creadas <= esta fecha (."),
    tag: Optional[list[str]] = Query(None, description="Filtrar memorias que contengan TODOS estos tags (AND lógico). Ejemplo: ?tag=landing&tag=status:approved"),
    expand_scope: bool = Query(False, description=". Audit log obligatorio."),
    actor: dict = Depends(get_current_user),
) -> MemoryListResponse:
    """Lista memorias recientes del actor con filtros y opt-in expand_scope.

    Filtros: workspace_id, project_id, user_id, agent_identifier, fecha_desde,
    fecha_hasta. workspace_id y project_id validados contra visible_*_ids
    (403 anti-IDOR coherente con /search). fecha_desde > fecha_hasta → 422.
    Visibility unificada via SQL function check_visibility (.
    expand_scope=true override jerárquico opt-in con audit log obligatorio
    . Restricción worker (no super, no CEO, sin lead_ws) +
    expand_scope=true + user_id ajeno → 403 (anti-fingerprinting).
    """
    if fecha_desde is not None and fecha_hasta is not None and fecha_desde > fecha_hasta:
        raise HTTPException(422, "fecha_desde cannot be after fecha_hasta")

    is_super = bool(actor.get("is_super"))
    user_id = int(actor["sub"])
    is_ceo = bool(actor.get("is_ceo"))
    org_id = actor.get("organization_id")
    lead_ws = list(actor.get("lead_workspaces") or [])

    # .
    if (expand_scope and user_id_filter is not None
            and user_id_filter != user_id
            and not is_super and not is_ceo and not lead_ws):
        raise HTTPException(
            403,
            "worker without elevated role cannot use expand_scope with user_id filter on another user",
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        if is_super:
            visible_projects: set[int] = set()
        else:
            visible_projects = await visible_project_ids(conn, actor)

        if project_id is not None and not is_super and project_id not in visible_projects:
            raise HTTPException(403, "no access to specified project")
        if workspace_id is not None and not is_super:
            visible_ws = await visible_workspace_ids(conn, actor)
            if workspace_id not in visible_ws:
                raise HTTPException(403, "no access to specified workspace")

        if not is_super and not visible_projects:
            # VS1 fix 
            # expand_scope=true, audit ANTES del early-return para no
            # bypasear la invariante "audit obligatorio expand_scope=true".
            if expand_scope:
                await conn.execute(
                    """
                    INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                    VALUES ($1, 'recent_expanded', 'memories_batch', $2, $3::jsonb, $4)
                    """,
                    user_id, str(uuid.uuid4()),
                    json.dumps({
                        "filters": {
                            "workspace_id": workspace_id,
                            "project_id": project_id,
                            "user_id": user_id_filter,
                            "agent_identifier": agent_identifier,
                            "fecha_desde": fecha_desde.isoformat() if fecha_desde else None,
                            "fecha_hasta": fecha_hasta.isoformat() if fecha_hasta else None,
                            "tag": tag,
                        },
                        "result_count": 0,
                        "actor_is_super": is_super,
                        "actor_is_ceo": is_ceo,
                        "no_visible_projects": True,
                    }), actor.get("organization_id"),
                )
            return MemoryListResponse(items=[], total=0, limit=limit, cursor_next=None)

        # Resolver agent_identifier → agent_id si filtro presente.
        target_agent_id: Optional[int] = None
        if agent_identifier is not None:
            target_agent_id = await conn.fetchval(
                "SELECT id FROM agents WHERE identifier = $1", agent_identifier
            )
            if target_agent_id is None:
                raise HTTPException(422, "agent_identifier not found")

        # Construcción WHERE dinámica con check_visibility unificado.
        where_parts = ["($1::bool OR m.project_id = ANY($2::int[]))"]
        params: list = [is_super, list(visible_projects)]
        idx = 3

        if project_id is not None:
            where_parts.append(f"m.project_id = ${idx}")
            params.append(project_id)
            idx += 1
        if workspace_id is not None:
            where_parts.append(f"m.workspace_id = ${idx}")
            params.append(workspace_id)
            idx += 1
        if user_id_filter is not None:
            where_parts.append(f"m.user_id = ${idx}")
            params.append(user_id_filter)
            idx += 1
        if target_agent_id is not None:
            where_parts.append(f"m.agent_id = ${idx}")
            params.append(target_agent_id)
            idx += 1
        if fecha_desde is not None:
            where_parts.append(f"m.created_at >= ${idx}")
            params.append(fecha_desde)
            idx += 1
        if fecha_hasta is not None:
            where_parts.append(f"m.created_at <= ${idx}")
            params.append(fecha_hasta)
            idx += 1
        if tag is not None:
            where_parts.append(f"m.tags @> ${idx}::text[]")
            params.append(tag)
            idx += 1

        # check_visibility (.
        where_parts.append(
            f"check_visibility("
            f"m.user_id, m.visibility::text, m.workspace_id, m.project_id, "
            f"${idx}, ${idx + 1}::bool, ${idx + 2}::bool, ${idx + 3}, ${idx + 4}::int[], ${idx + 5}::bool"
            f")"
        )
        params.extend([user_id, is_super, is_ceo, org_id, lead_ws, expand_scope])
        idx += 6

        params_for_count = params[:]  # Copia antes de añadir LIMIT.
        params.append(limit)
        limit_idx = idx

        rows = await conn.fetch(
            f"""
            SELECT m.*, a.identifier AS agent_identifier
            FROM memories m
            LEFT JOIN agents a ON a.id = m.agent_id
            WHERE {" AND ".join(where_parts)}
            ORDER BY m.created_at DESC
            LIMIT ${limit_idx}
            """,
            *params,
        )
        total_row = await conn.fetchval(
            f"""
            SELECT count(*) FROM memories m
            WHERE {" AND ".join(where_parts)}
            """,
            *params_for_count,
        )

        # Audit log .
        if expand_scope:
            await conn.execute(
                """
                INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                VALUES ($1, 'recent_expanded', 'memories_batch', $2, $3::jsonb, $4)
                """,
                user_id, str(uuid.uuid4()),
                json.dumps({
                    "filters": {
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "user_id": user_id_filter,
                        "agent_identifier": agent_identifier,
                        "fecha_desde": fecha_desde.isoformat() if fecha_desde else None,
                        "fecha_hasta": fecha_hasta.isoformat() if fecha_hasta else None,
                        "tag": tag,
                    },
                    "result_count": len(rows),
                    "actor_is_super": is_super,
                    "actor_is_ceo": is_ceo,
                }), actor.get("organization_id"),
            )

    items = [_row_to_response(r) for r in rows]
    return MemoryListResponse(items=items, total=total_row, limit=limit, cursor_next=None)


@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: UUID,
    expand_scope: bool = Query(False, description=". Audit log obligatorio."),
    actor: dict = Depends(get_current_user),
) -> MemoryResponse:
    """Lookup por UUID. 
    acepta — opción B consenso, coherente con búsqueda).

    Sin expand_scope: comportamiento estricto (private solo creator/CEO/super).
    Con expand_scope: override jerárquica (Lead/project_lead ven private del
    scope si están sobre el creador en el árbol). Audit log obligatorio.
    """
    is_super = bool(actor.get("is_super"))
    is_ceo = bool(actor.get("is_ceo"))
    user_id_actor = int(actor["sub"])
    org_id = actor.get("organization_id")
    lead_ws = list(actor.get("lead_workspaces") or [])

    pool = await get_pool()
    async with pool.acquire() as conn:
        # check_visibility en SQL — comportamiento unificado con search/recent.
        row = await conn.fetchrow(
            """
            SELECT m.*, a.identifier AS agent_identifier
            FROM memories m
            LEFT JOIN agents a ON a.id = m.agent_id
            WHERE m.id = $1
              AND check_visibility(
                m.user_id, m.visibility::text, m.workspace_id, m.project_id,
                $2, $3::bool, $4::bool, $5, $6::int[], $7::bool
              )
            """,
            memory_id, user_id_actor, is_super, is_ceo, org_id, lead_ws, expand_scope,
        )
        if row is None:
            # Anti-IDOR: 403 unificado para "no existe" y "sin acceso".
            raise HTTPException(403, "no read access to this memory")
        # Track access.
        await conn.execute(
            "UPDATE memories SET access_count = access_count + 1, last_accessed = now() WHERE id = $1",
            memory_id,
        )
        # Audit log .
        if expand_scope:
            await conn.execute(
                """
                INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                VALUES ($1, 'memory_read_expanded', 'memory', $2, $3::jsonb, $4)
                """,
                user_id_actor, str(memory_id),
                json.dumps({
                    "memory_visibility": str(row["visibility"]),
                    "memory_creator": row["user_id"],
                    "actor_is_super": is_super,
                    "actor_is_ceo": is_ceo,
                }), actor.get("organization_id"),
            )
    row = dict(row)
    row["access_count"] = row["access_count"] + 1
    row["last_accessed"] = datetime.now(timezone.utc)
    return _row_to_response(row)


@router.put("/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: UUID,
    body: MemoryUpdate,
    actor: dict = Depends(get_current_user),
) -> MemoryResponse:
    """Actualiza memoria. Re-embed solo si content cambia.

    VS2 fix  — embed
    FUERA del pool.acquire(). Flujo: SELECT + permisos + validar (pool corto)
    → libero pool → embed si content cambio → re-acquire para UPDATE atomico.
    """
    pool = await get_pool()

    # FASE 1 — leer estado + permisos + validar fields (pool corto)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT m.*, a.identifier AS agent_identifier
            FROM memories m
            LEFT JOIN agents a ON a.id = m.agent_id
            WHERE m.id = $1
            """,
            memory_id,
        )
        # IC2 fix →403 anti-IDOR coherente
        # con GET /memories/{id} (un actor no puede distinguir "no existe"
        # vs "sin acceso" para el mismo UUID via PUT).
        if row is None:
            raise HTTPException(403, "no access to this memory")
        if not await can_write_memory(conn, actor, dict(row)):
            raise HTTPException(403, "no write access to this memory")

        # visibility downgrade paradox. Si un CEO/Lead cambia
        # una memoria public a private, despues VS5 le quita write access — la
        # memoria queda "congelada" sin rastro (sin audit log). Decision: el
        # visibility solo lo cambia el creador o super.
        if body.visibility is not None and body.visibility != row["visibility"]:
            if not actor.get("is_super") and row["user_id"] != int(actor["sub"]):
                raise HTTPException(
                    403,
                    "only the creator or super can change visibility",
                )

        # Construir sets dinamicamente — solo campos no-None.
        sets: list[str] = []
        params: list = [memory_id]
        i = 2
        content_changed = body.content is not None and body.content != row["content"]
        if body.content is not None:
            sets.append(f"content = ${i}"); params.append(body.content); i += 1
        if body.type is not None:
            wb = await conn.fetchval(
                "SELECT base_weight FROM memory_type_config WHERE type=$1", body.type
            )
            if wb is None:
                raise HTTPException(422, f"unknown memory type: {body.type}")
            # aclaracion: actualizamos weight_base pero NO weight.
            # weight es runtime (modificado por accesos / decay en Fase 5);
            # weight_base es la asignacion base del tipo. Esa asimetria es
            # intencional — el cambio de tipo resetea la "base" pero preserva
            # la trayectoria de weight acumulada por uso.
            sets.append(f"type = ${i}::memory_type"); params.append(body.type); i += 1
            sets.append(f"weight_base = ${i}"); params.append(float(wb)); i += 1
        if body.visibility is not None:
            sets.append(f"visibility = ${i}::visibility"); params.append(body.visibility); i += 1
        if body.tags is not None:
            sets.append(f"tags = ${i}"); params.append(body.tags); i += 1
        if body.media_path is not None:
            sets.append(f"media_path = ${i}"); params.append(body.media_path); i += 1
        if body.metadata is not None:
            sets.append(f"metadata = ${i}::jsonb"); params.append(json.dumps(body.metadata)); i += 1
        if not sets:
            raise HTTPException(400, "no fields to update")
        sets.append("updated_at = now()")
    # Pool liberado.

    # FASE 2 — embed FUERA del pool si content cambio.
    embedding_literal: Optional[str] = None
    if content_changed:
        embedding_literal = await embed_text(body.content, prompt_name="passage")

    # FASE 3 — UPDATE atomico (con embedding si aplica) en una sola query.
    async with pool.acquire() as conn:
        if content_changed:
            sets.append(f"embedding = ${i}::vector"); params.append(embedding_literal); i += 1
            sets.append(f"embedding_model = ${i}"); params.append(EMBEDDING_MODEL_TAG); i += 1
        sql = f"""
            WITH updated AS (
              UPDATE memories SET {', '.join(sets)} WHERE id = $1 RETURNING *
            )
            SELECT u.*, a.identifier AS agent_identifier
            FROM updated u
            LEFT JOIN agents a ON a.id = u.agent_id
        """
        new_row = await conn.fetchrow(sql, *params)
        if new_row is None:
            raise HTTPException(404, "memory not found or deleted concurrently")
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'update_memory', 'memory', $2, $3::jsonb, $4)""",
            int(actor["sub"]), str(memory_id),
            json.dumps({"fields_updated": list(body.model_fields_set)}),
            actor.get("organization_id"),
        )

    return _row_to_response(new_row)


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: UUID,
    actor: dict = Depends(get_current_user),
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT m.*, a.identifier AS agent_identifier
            FROM memories m
            LEFT JOIN agents a ON a.id = m.agent_id
            WHERE m.id = $1
            """,
            memory_id,
        )
        if row is None:
            raise HTTPException(403, "no access to this memory")
        if not await can_write_memory(conn, actor, dict(row)):
            raise HTTPException(403, "no access to this memory")
        # Soft delete: copiar a trash + DELETE de memories
        async with conn.transaction():
            original = dict(row)
            # Convertir tipos que JSONB no acepta directos
            for k, v in list(original.items()):
                if isinstance(v, datetime):
                    original[k] = v.isoformat()
                elif isinstance(v, UUID):
                    original[k] = str(v)
            # embedding (vector) viene como string en asyncpg si está; lo dejamos
            original.pop("embedding", None)
            # defense-in-depth: aunque la validacion en POST/PUT
            # impide null bytes nuevos, memorias creadas antes del fix podrian
            # tener \x00 en content. Strip de \\u0000 del JSON serializado para
            # que JSONB nunca lo rechace en el INSERT a trash.
            json_str = json.dumps(original).replace("\\u0000", "")
            await conn.execute(
                """
                INSERT INTO trash (id, original_table, original_data, deleted_by)
                VALUES ($1, 'memories', $2::jsonb, $3)
                """,
                row["id"], json_str, int(actor["sub"]),
            )
            await conn.execute("DELETE FROM memories WHERE id = $1", memory_id)
            await conn.execute(
                """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                VALUES ($1, 'delete_memory', 'memory', $2, $3::jsonb, $4)""",
                int(actor["sub"]), str(memory_id),
                json.dumps({"type": row.get("type"), "workspace_id": row.get("workspace_id"), "project_id": row.get("project_id")}),
                actor.get("organization_id"),
            )


@router.put("/{memory_id}/links/{document_id}/validate")
async def validate_link(
    memory_id: UUID,
    document_id: UUID,
    actor: dict = Depends(get_current_user),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        mem = await conn.fetchrow("SELECT project_id, user_id FROM memories WHERE id = $1", memory_id)
        if mem is None:
            raise HTTPException(403, "no access to this memory")
        if not actor.get("is_super"):
            if mem["user_id"] != int(actor["sub"]):
                raise HTTPException(403, "no access to this memory")
        result = await conn.execute(
            """
            UPDATE memory_document_links
            SET validated = true
            WHERE memory_id = $1 AND document_id = $2
            """,
            memory_id, document_id,
        )
        if result == "UPDATE 0":
            raise HTTPException(404, "Link not found")
    return {"status": "ok", "memory_id": str(memory_id), "document_id": str(document_id), "validated": True}


# ---------------------------------------------------------------------------
# Task 5.20 — Unarchive memory
# ---------------------------------------------------------------------------

@router.put("/{memory_id}/unarchive")
async def unarchive_memory(
    memory_id: UUID,
    actor: dict = Depends(get_current_user),
):
    """Transition a memory from archived → active."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        mem = await conn.fetchrow("SELECT project_id, user_id FROM memories WHERE id = $1", memory_id)
        if mem is None:
            raise HTTPException(403, "no access to this memory")
        if not actor.get("is_super"):
            if mem["user_id"] != int(actor["sub"]):
                raise HTTPException(403, "no access to this memory")
        result = await conn.execute(
            "UPDATE memories SET staleness = 'active', updated_at = now() WHERE id = $1 AND staleness = 'archived'",
            memory_id,
        )
        if result == "UPDATE 0":
            raise HTTPException(404, "Memory not archived")
    return {"status": "ok", "memory_id": str(memory_id), "staleness": "active"}


# ---------------------------------------------------------------------------
# B5 — PUT /memories/{id}/staleness
# ---------------------------------------------------------------------------

class StalenessUpdate(BaseModel):
    staleness: Literal["active", "stale", "dormant", "archived"]


@router.put("/{memory_id}/staleness")
async def update_staleness(
    memory_id: UUID,
    body: StalenessUpdate,
    actor: dict = Depends(get_current_user),
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, project_id, workspace_id, visibility, staleness FROM memories WHERE id = $1 AND staleness != 'archived'",
            memory_id,
        )
        if row is None or not await can_write_memory(conn, actor, dict(row)):
            raise HTTPException(403, "no access to this memory")
        async with conn.transaction():
            await conn.execute(
                "UPDATE memories SET staleness = $1, updated_at = now() WHERE id = $2",
                body.staleness, memory_id,
            )
            await conn.execute(
                """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                VALUES ($1, 'update_staleness', 'memory', $2, $3::jsonb, $4)""",
                int(actor["sub"]), str(memory_id),
                json.dumps({"staleness": body.staleness}),
                actor.get("organization_id"),
            )
    return {"memory_id": str(memory_id), "staleness": body.staleness}


# ---------------------------------------------------------------------------
# B6 — Preview (GLiNER dry-run, no persist)
# ---------------------------------------------------------------------------

class PreviewRequest(BaseModel):
    content: str = Field(..., min_length=3, max_length=16000)

    @field_validator("content")
    @classmethod
    def _v_content(cls, v: str) -> str:
        return _no_null_bytes(v, "content")


@router.post("/preview")
async def preview_memory(
    body: PreviewRequest,
    actor: dict = Depends(get_current_user),
) -> dict:
    """Dry-run GLiNER entity extraction without persisting. For Templates screen."""
    import logging as _logging
    from gliner_service import extract_entities
    try:
        entities = await extract_entities(body.content)
    except Exception as exc:
        _logging.getLogger("ecodb.preview").warning("GLiNER preview failed: %r", exc)
        entities = []
    unique = list({e["text"]: e for e in (entities or [])}.values())
    suggested_triples = []
    for e in unique:
        suggested_triples.append({
            "subject": e["text"],
            "predicate": "is_a",
            "object": e.get("label", "unknown"),
        })
    return {
        "entities": unique,
        "entity_count": len(unique),
        "suggested_triples": suggested_triples,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_response(row, agent_identifier=None) -> MemoryResponse:
    return MemoryResponse(
        id=row["id"],
        user_id=row["user_id"],
        agent_identifier=agent_identifier or row.get("agent_identifier"),
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        type=row["type"],
        content_type=row["content_type"],
        visibility=row["visibility"],
        content=row["content"],
        tags=list(row["tags"]),
        weight=float(row["weight"]),
        weight_base=float(row["weight_base"]),
        access_count=row["access_count"],
        media_path=row["media_path"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_accessed=row["last_accessed"],
        summary=row.get("summary"),
        staleness=row.get("staleness"),
        foresight_start=row.get("foresight_start"),
        foresight_end=row.get("foresight_end"),
        metadata=json.loads(row["metadata"]) if isinstance(row.get("metadata"), str) else (dict(row["metadata"]) if row.get("metadata") else None),
    )
