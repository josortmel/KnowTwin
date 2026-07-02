"""Endpoints de grafo SQL+AGE — .4 + §4 patron dual.

Endpoints:
- POST   /graph/triples          crea tripleta atomica SQL + AGE.
- POST   /graph/triples/batch    crea N tripletas en una sola transaccion.
- GET    /graph/neighbors/{node} vecinos a 1-N saltos via Cypher.
- GET    /graph/path             camino mas corto entre dos nodos via Cypher.
- GET    /graph/search           fuzzy search por nombre con pg_trgm.
- DELETE /graph/triples/{id}     borra tripleta (SQL + AGE).
- GET    /graph/stats            count nodes/triples/predicates.

Modelo del grafo (plan v3 §4.0):
- AGE es extension PostgreSQL → opera en la misma transaccion ACID que SQL.
- Tabla `nodes` (SQL) y `triples` (SQL) son respaldo relacional + indices.
- Grafo activo en AGE: label `:Entity` para nodos, label `:RELATES_TO` para
  aristas con propiedad `predicate`.
- Cualquier operacion que escribe en AGE escribe tambien en SQL en la misma
  transaccion. Si AGE falla → rollback.

Cypher injection: PROHIBIDO interpolar strings en queries Cypher. Usar el 3er
argumento de cypher() como `$1::agtype` con JSON parametrizado por Python.

Permisos en este sprint (
- Cualquier user autenticado puede leer/escribir el grafo (es shared a nivel
  sistema, plataforma-wide single-tenant).
- Scoping por workspace/org del grafo viene en Tarea 2.x cuando se decida si
  hay un grafo por org o uno global.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from auth import get_current_user
from db import get_pool
from permissions import no_null_bytes as _no_null_bytes


router = APIRouter(prefix="/graph", tags=["graph"])

GRAPH_NAME = "knowtwin_graph"
MAX_NODE_NAME_LEN = 500
MAX_PREDICATE_LEN = 200
MAX_BATCH = 100
_MAX_MERGE_CHAIN_DEPTH = 50


# ---------------------------------------------------------------------------
# agtype helpers
# ---------------------------------------------------------------------------

def _strip_agtype(value: str) -> str:
    """agtype literales vienen como `"text"`, `123`, `{...}::vertex`, `{...}::edge`.
    Strip comillas y sufijos `::type` si aparecen.

    si el string es un literal entre comillas (`"..."`),
    NO procesar `::` interno — un nombre como `"Python::typing"` debe preservarse.
    Solo se strippa `::type` cuando el valor NO esta entre comillas (objetos
    vertex/edge/path).
    """
    if value is None:
        return ""
    s = str(value).strip()
    # String literal: strip comillas, preservar contenido (incluyendo :: interno)
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    # No es string literal: puede tener sufijo ::vertex/::edge/::path. Strip por
    # la derecha para no afectar :: dentro del contenido.
    if "::" in s:
        s = s.rsplit("::", 1)[0]
        if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
            return s[1:-1]
    return s


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TripleCreate(BaseModel):
    subject: str = Field(..., min_length=1, max_length=MAX_NODE_NAME_LEN)
    predicate: str = Field(..., min_length=1, max_length=MAX_PREDICATE_LEN)
    object: str = Field(..., min_length=1, max_length=MAX_NODE_NAME_LEN)
    author: Optional[str] = Field(None, max_length=200)

    @field_validator("subject", "predicate", "object", "author")
    @classmethod
    def _no_nb(cls, v):
        return _no_null_bytes(v, "field") if v is not None else v


class TripleResponse(BaseModel):
    id: int
    subject_id: int
    subject_name: str
    predicate: str
    object_id: int
    object_name: str
    author: Optional[str]


class TripleBatch(BaseModel):
    triples: list[TripleCreate] = Field(..., min_length=1, max_length=MAX_BATCH)


class TripleBatchResponse(BaseModel):
    created: list[TripleResponse]
    skipped_duplicates: int


class NeighborsResponse(BaseModel):
    center: str
    depth: int
    neighbors: list[str]


class PathResponse(BaseModel):
    source: str
    target: str
    path: list[str]
    length: int


class GraphSearchResponse(BaseModel):
    query: str
    matches: list[dict]


class GraphStats(BaseModel):
    nodes: int
    triples: int
    distinct_predicates: int


# ---------------------------------------------------------------------------
# Internal helpers — SQL + AGE atomic
# ---------------------------------------------------------------------------

async def _ensure_node(conn, name: str) -> int:
    """Devuelve el `nodes.id` SQL del nodo, creandolo si no existe.

    TOCTOU race condition. Dos requests concurrentes con el
    mismo node_name nuevo causaban UNIQUE violation. Fix: ON CONFLICT DO NOTHING
    + fallback SELECT. El INSERT en AGE solo se ejecuta si el INSERT SQL fue
    realmente nuevo (RETURNING devolvio fila); si la fila ya existia (otro
    proceso la creo entre el SELECT y el INSERT), saltamos el AGE create.
    """
    async def _age_create(n: str, sid: int) -> None:
        params = json.dumps({"name": n, "sql_id": sid})
        await conn.execute(
            f"""
            SELECT * FROM cypher('{GRAPH_NAME}', $$
                CREATE (n:Entity {{name: $name, sql_id: $sql_id}})
                RETURN id(n)
            $$, $1::agtype) AS (node_id agtype)
            """,
            params,
        )

    # 
    # unificar nodos por casing. "Eco" y "eco" → mismo nodo. El nombre display
    # se preserva del primer INSERT (el que creó el nodo).
    name = name[:MAX_NODE_NAME_LEN]
    # Prevent concurrent duplicate creation — must be inside a transaction.
    await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", name)
    inserted = await conn.fetchrow(
        """
        INSERT INTO nodes (name) VALUES ($1)
        ON CONFLICT (name_canonical) DO NOTHING
        RETURNING id
        """,
        name,
    )
    if inserted is None:
        existing = await conn.fetchrow(
            "SELECT id FROM nodes WHERE name_canonical = lower($1)", name
        )
        if existing is None:
            raise RuntimeError(f"node {name!r} disappeared during concurrent operation")
        sql_id = existing["id"]
        # Check if AGE node exists with this sql_id, create if missing
        params_check = json.dumps({"sql_id": sql_id})
        age_exists = await conn.fetchrow(
            f"""
            SELECT * FROM cypher('{GRAPH_NAME}', $$
                MATCH (n:Entity {{sql_id: $sql_id}})
                RETURN id(n)
            $$, $1::agtype) AS (node_id agtype)
            """,
            params_check,
        )
        if age_exists is None:
            try:
                await _age_create(name, sql_id)
            except Exception as _age_dup:
                logging.getLogger("ecodb.graph").warning(
                    "_ensure_node: AGE create failed for %r (sql_id=%d): %r", name, sql_id, _age_dup
                )
        return sql_id
    sql_id = inserted["id"]
    # AGE node created by trg_age_sync_insert trigger — no manual _age_create here.
    return sql_id


async def link_entities_from_content(conn, memory_id, content: str, pool=None) -> int:
    """.

    Decisiones :
    - GLiNER falla o devuelve 0 entidades → return 0, NO levanta. La memoria
      sigue creada sin links (skip + log graceful).
    - get_or_create case-sensitive — "Acme" y "ACME" son nodos distintos.
      Canonización estricta es Fase 5, no 3.0b.
    - Entidades duplicadas dentro del mismo content (GLiNER puede detectar la
      misma palabra varias veces) se deduplican antes del link.
    - ON CONFLICT DO NOTHING en memory_entity_links — idempotente para
      migración retroactiva (.

    Returns: número de entity_links creados (0 si GLiNER falló o no encontró).
    Si AGE falla a mitad de procesamiento, la excepción se propaga — el caller
    debe manejarla (rollback de su transaction).
    """
    # Import lazy para no acoplar graph.py a gliner_service en imports top-level
    # — facilita testing y desacoplamiento.
    from gliner_service import extract_entities, detect_alias_candidates
    import logging
    _log = logging.getLogger("ecodb.gliner_link")

    try:
        entities = await extract_entities(content)
    except Exception as exc:
        # logger.warning explícito
        # en lugar de silencio total. Antes este except suprimia errores
        # catastróficos (ImportError, RuntimeError, OOM torch/transformers)
        # sin rastro. Memoria YA creada, no rollback — pero el operador
        # necesita saber si GLiNER esta roto.
        _log.warning("link_entities_from_content: GLiNER extract_entities failed for memory=%s: %r", memory_id, exc)
        return 0

    if not entities:
        return 0

    # Sort entities by name for consistent advisory lock order (prevents deadlock)
    entities = sorted(entities, key=lambda e: e["text"].lower())
    # Deduplicar por nombre exacto preservando orden sorted (dict.fromkeys mantiene
    # insertion order, elimina duplicados — set no garantiza orden estable).
    unique_names = list(dict.fromkeys(e["text"] for e in entities))

    count = 0
    async with conn.transaction():
        for name in unique_names:
            if not name or not name.strip():
                continue
            # cap MAX_NODE_NAME_LEN
            # consistente con la ruta /graph/triples (api-public 500 chars).
            # Sin cap, GLiNER puede devolver spans largos crafteados que
            # terminan en nodos AGE con nombres descomunales — inconsistencia
            # de schema + DoS parcial.
            if len(name) > MAX_NODE_NAME_LEN:
                _log.warning("link_entities_from_content: skipping entity name >%d chars (memory=%s)", MAX_NODE_NAME_LEN, memory_id)
                continue
            node_sql_id = await _ensure_node(conn, name)
            await conn.execute(
                """
                INSERT INTO memory_entity_links (memory_id, entity_node_id)
                VALUES ($1, $2)
                ON CONFLICT (memory_id, entity_node_id) DO NOTHING
                """,
                memory_id, node_sql_id,
            )
            count += 1

    # Detect alias candidates from extracted entities (best-effort, outside tx)
    if pool is not None and entities:
        try:
            await detect_alias_candidates(entities, pool)
        except Exception as _alias_exc:
            _log.warning("link_entities_from_content: alias detection failed for memory=%s: %r", memory_id, _alias_exc)

    return count


COOCCURRENCE_PREDICATE = "related_to"
COOCCURRENCE_AUTHOR = "system:cooccurrence"


async def update_cooccurrence_triples(conn, entity_node_ids: list[int]) -> int:
    """Create related_to triples for entity pairs co-occurring in >=THRESHOLD memories.

    Called after link_entities_from_content. For each pair of entities in this
    memory, checks if they now co-occur in >=THRESHOLD memories total. If so,
    creates a related_to triple (idempotent, ON CONFLICT DO NOTHING).
    Dual write SQL+AGE per triple. AGE failure propagates — caller's
    transaction rollbacks both SQL and AGE atomically.
    """
    from settings import COOCCURRENCE_THRESHOLD

    if len(entity_node_ids) < 2:
        return 0

    MAX_COOC_ENTITIES = 50
    if len(entity_node_ids) > MAX_COOC_ENTITIES:
        entity_node_ids = entity_node_ids[:MAX_COOC_ENTITIES]

    created = 0
    for i, eid_a in enumerate(entity_node_ids):
        for eid_b in entity_node_ids[i + 1:]:
            a, b = min(eid_a, eid_b), max(eid_a, eid_b)
            co_count = await conn.fetchval("""
                SELECT count(*) FROM (
                    SELECT mel1.memory_id
                    FROM memory_entity_links mel1
                    JOIN memory_entity_links mel2 ON mel1.memory_id = mel2.memory_id
                    WHERE mel1.entity_node_id = $1 AND mel2.entity_node_id = $2
                ) sub
            """, a, b)

            if co_count < COOCCURRENCE_THRESHOLD:
                continue

            row = await conn.fetchrow("""
                INSERT INTO triples (subject_id, predicate, object_id, author)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (subject_id, predicate, object_id) DO NOTHING
                RETURNING id
            """, a, COOCCURRENCE_PREDICATE, b, COOCCURRENCE_AUTHOR)

            if row is not None:
                await _create_age_edge(conn, a, COOCCURRENCE_PREDICATE, b)
                created += 1

    return created


async def _create_age_edge(conn, subject_sql_id: int, predicate: str, object_sql_id: int) -> None:
    """Crea la arista en AGE entre los nodos identificados por sql_id."""
    params = json.dumps({"sid": subject_sql_id, "oid": object_sql_id, "pred": predicate})
    await conn.execute(
        f"""
        SELECT * FROM cypher('{GRAPH_NAME}', $$
            MATCH (s:Entity {{sql_id: $sid}}), (o:Entity {{sql_id: $oid}})
            CREATE (s)-[r:RELATES_TO {{predicate: $pred}}]->(o)
            RETURN id(r)
        $$, $1::agtype) AS (edge_id agtype)
        """,
        params,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/triples", response_model=TripleResponse, status_code=201)
async def create_triple(body: TripleCreate, actor: dict = Depends(get_current_user)) -> TripleResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            subj_id = await _ensure_node(conn, body.subject)
            obj_id = await _ensure_node(conn, body.object)
            # ON CONFLICT DO NOTHING evita romper la transaccion si la tripleta
            # ya existe — devuelve None y respondemos 409 limpio.
            row = await conn.fetchrow(
                """
                INSERT INTO triples (subject_id, predicate, object_id, author)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (subject_id, predicate, object_id) DO NOTHING
                RETURNING id
                """,
                subj_id, body.predicate, obj_id, body.author,
            )
            if row is None:
                raise HTTPException(409, "triple already exists")
            await _create_age_edge(conn, subj_id, body.predicate, obj_id)
            triple_id = row["id"]
            await conn.execute(
                """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                VALUES ($1, 'save_triple', 'triple', $2, $3::jsonb, $4)""",
                int(actor["sub"]), str(triple_id),
                json.dumps({"subject": body.subject, "predicate": body.predicate, "object": body.object}),
                actor.get("organization_id"),
            )
    return TripleResponse(
        id=triple_id,
        subject_id=subj_id,
        subject_name=body.subject,
        predicate=body.predicate,
        object_id=obj_id,
        object_name=body.object,
        author=body.author,
    )


@router.post("/triples/batch", response_model=TripleBatchResponse, status_code=201)
async def create_triples_batch(body: TripleBatch, actor: dict = Depends(get_current_user)) -> TripleBatchResponse:
    created: list[TripleResponse] = []
    skipped = 0
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for triple in body.triples:
                subj_id = await _ensure_node(conn, triple.subject)
                obj_id = await _ensure_node(conn, triple.object)
                # ON CONFLICT DO NOTHING — duplicados se cuentan, no rompen la tx.
                row = await conn.fetchrow(
                    """
                    INSERT INTO triples (subject_id, predicate, object_id, author)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (subject_id, predicate, object_id) DO NOTHING
                    RETURNING id
                    """,
                    subj_id, triple.predicate, obj_id, triple.author,
                )
                if row is None:
                    skipped += 1
                    continue
                await _create_age_edge(conn, subj_id, triple.predicate, obj_id)
                created.append(TripleResponse(
                    id=row["id"],
                    subject_id=subj_id,
                    subject_name=triple.subject,
                    predicate=triple.predicate,
                    object_id=obj_id,
                    object_name=triple.object,
                    author=triple.author,
                ))
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'save_triples_batch', 'triple', $2, $3::jsonb, $4)""",
            int(actor["sub"]), str(uuid.uuid4()),
            json.dumps({"created_count": len(created), "skipped_count": skipped, "triple_ids": [t.id for t in created]}),
            actor.get("organization_id"),
        )
    return TripleBatchResponse(created=created, skipped_duplicates=skipped)


@router.get("/neighbors/{node_name}", response_model=NeighborsResponse)
async def neighbors(
    node_name: str,
    depth: int = Query(1, ge=1, le=5),
    actor: dict = Depends(get_current_user),
) -> NeighborsResponse:
    if "\x00" in node_name:
        raise HTTPException(400, "node_name cannot contain null bytes")
    if len(node_name) > MAX_NODE_NAME_LEN:
        raise HTTPException(400, "node_name too long")
    pool = await get_pool()
    async with pool.acquire() as conn:
        # OBS-2 (verificador L1): si el nodo no existe en SQL, 404 explicito
        # en lugar de devolver lista vacia (que confunde "nodo inexistente"
        # con "nodo aislado sin vecinos").
        node_exists = await conn.fetchval("SELECT 1 FROM nodes WHERE lower(name) = lower($1)", node_name)
        if not node_exists:
            raise HTTPException(404, "node not found")
        params = json.dumps({"name": node_name})
        rows = await conn.fetch(
            f"""
            SELECT * FROM cypher('{GRAPH_NAME}', $$
                MATCH (start:Entity {{name: $name}})-[*1..{depth}]-(connected:Entity)
                WHERE start <> connected
                RETURN DISTINCT connected.name AS n
            $$, $1::agtype) AS (n agtype)
            """,
            params,
        )
    return NeighborsResponse(
        center=node_name,
        depth=depth,
        neighbors=[_strip_agtype(r["n"]) for r in rows],
    )


@router.get("/path", response_model=PathResponse)
async def shortest_path(
    source: str = Query(..., min_length=1, max_length=MAX_NODE_NAME_LEN),
    target: str = Query(..., min_length=1, max_length=MAX_NODE_NAME_LEN),
    max_depth: int = Query(6, ge=1, le=10),
    actor: dict = Depends(get_current_user),
) -> PathResponse:
    """BFS iterativo desde source hasta target.

    AGE no soporta `shortestPath()` (no esta implementado en la version actual).
    Workaround: iterar depth 1..max_depth, buscar UN path en cada iteracion,
    devolver el primero encontrado (que es el mas corto por construccion).
    """
    if "\x00" in source or "\x00" in target:
        raise HTTPException(400, "node names cannot contain null bytes")
    # OBS-1 (verificador L1): path de un nodo a si mismo es path trivial de
    # length 0. Coherente con cliente que pregunta "¿hay camino A→A?" sin que
    # el server diga 404. Solo si el nodo existe en SQL.
    pool = await get_pool()
    async with pool.acquire() as conn:
        if source == target:
            exists = await conn.fetchval("SELECT 1 FROM nodes WHERE name = $1", source)
            if not exists:
                raise HTTPException(404, "source node not found")
            return PathResponse(source=source, target=target, path=[source], length=0)
        params = json.dumps({"src": source, "tgt": target})
        # Verificar existencia de ambos nodos antes del BFS
        src_exists = await conn.fetchval("SELECT 1 FROM nodes WHERE name = $1", source)
        if not src_exists:
            raise HTTPException(404, f"source node '{source}' not found in graph")
        tgt_exists = await conn.fetchval("SELECT 1 FROM nodes WHERE name = $1", target)
        if not tgt_exists:
            raise HTTPException(404, f"target node '{target}' not found in graph")
        for depth in range(1, max_depth + 1):
            rows = await conn.fetch(
                f"""
                SELECT * FROM cypher('{GRAPH_NAME}', $$
                    MATCH p = (s:Entity {{name: $src}})-[*1..{depth}]-(t:Entity {{name: $tgt}})
                    WITH p LIMIT 1
                    UNWIND nodes(p) AS n
                    RETURN n.name
                $$, $1::agtype) AS (name agtype)
                """,
                params,
            )
            if rows:
                nodes_in_path = [_strip_agtype(r["name"]) for r in rows]
                return PathResponse(
                    source=source,
                    target=target,
                    path=nodes_in_path,
                    length=max(0, len(nodes_in_path) - 1),
                )
    raise HTTPException(404, "no path between source and target")


@router.get("/search", response_model=GraphSearchResponse)
async def search_nodes(
    # pg_trgm GIN index requiere >=3 chars para extraer
    # trigramas. Con q < 3 caracteres, Postgres haria seq scan completo de
    # nodes — DoS facil con grafos grandes. Forzar minimo 3.
    q: str = Query(..., min_length=3, max_length=MAX_NODE_NAME_LEN),
    limit: int = Query(20, ge=1, le=100),
    actor: dict = Depends(get_current_user),
) -> GraphSearchResponse:
    """Fuzzy search por nombre. Combina ILIKE wildcard (substring match) con
    pg_trgm similarity para ranking. ILIKE captura "Cerv" en "pytest-Cervantes"
    sin depender del threshold de pg_trgm que es exigente con prefijos largos."""
    if "\x00" in q:
        raise HTTPException(400, "query cannot contain null bytes")
    pool = await get_pool()
    async with pool.acquire() as conn:
        pattern = f"%{q}%"
        rows = await conn.fetch(
            """
            SELECT id, name, similarity(name, $1) AS sim
            FROM nodes
            WHERE name ILIKE $2
            ORDER BY sim DESC, length(name) ASC
            LIMIT $3
            """,
            q, pattern, limit,
        )
    matches = [{"id": r["id"], "name": r["name"], "similarity": float(r["sim"])} for r in rows]
    return GraphSearchResponse(query=q, matches=matches)


@router.delete("/triples/{triple_id}", status_code=204)
async def delete_triple(triple_id: int, actor: dict = Depends(get_current_user)) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT t.id, t.predicate, ns.id AS sid, no.id AS oid
                FROM triples t
                JOIN nodes ns ON ns.id = t.subject_id
                JOIN nodes no ON no.id = t.object_id
                WHERE t.id = $1
                """,
                triple_id,
            )
            if row is None:
                raise HTTPException(404, "triple not found")
            # Borrar arista AGE primero. Si solo hay una arista entre los nodos
            # con ese predicado, se borra; si hay duplicados (no deberian con
            # UNIQUE en SQL) se borra el primero — comportamiento aceptable.
            params = json.dumps({"sid": row["sid"], "oid": row["oid"], "pred": row["predicate"]})
            await conn.execute(
                f"""
                SELECT * FROM cypher('{GRAPH_NAME}', $$
                    MATCH (s:Entity {{sql_id: $sid}})-[r:RELATES_TO {{predicate: $pred}}]->(o:Entity {{sql_id: $oid}})
                    DELETE r
                    RETURN 1
                $$, $1::agtype) AS (ok agtype)
                """,
                params,
            )
            await conn.execute("DELETE FROM triples WHERE id = $1", triple_id)
            await conn.execute(
                """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                VALUES ($1, 'delete_triple', 'triple', $2, $3::jsonb, $4)""",
                int(actor["sub"]), str(triple_id),
                json.dumps({"predicate": row["predicate"]}),
                actor.get("organization_id"),
            )


@router.get("/stats", response_model=GraphStats)
async def graph_stats(actor: dict = Depends(get_current_user)) -> GraphStats:
    pool = await get_pool()
    async with pool.acquire() as conn:
        nodes_count = await conn.fetchval("SELECT count(*) FROM nodes")
        triples_count = await conn.fetchval("SELECT count(*) FROM triples")
        preds_count = await conn.fetchval("SELECT count(DISTINCT predicate) FROM triples")
    return GraphStats(
        nodes=nodes_count,
        triples=triples_count,
        distinct_predicates=preds_count,
    )


# ---------------------------------------------------------------------------
# Fase 3b — Predicate governance endpoints
# ---------------------------------------------------------------------------

class PredicateResolveResponse(BaseModel):
    canonical: Optional[str] = None
    confidence: float = 0.0
    method: str = "none"
    original: str = ""

class AliasEntry(BaseModel):
    alias: str
    canonical: str
    domain: Optional[str] = None

class AliasListResponse(BaseModel):
    aliases: list[AliasEntry]


@router.get("/predicates/resolve", response_model=PredicateResolveResponse)
async def resolve_predicate(
    predicate: str = Query(..., min_length=1, max_length=200),
    subject_type: str = Query("unknown"),
    object_type: str = Query("unknown"),
    actor: dict = Depends(get_current_user),
) -> PredicateResolveResponse:
    """Resolve free-text predicate to canonical via 3 stages:
    1. Exact match in predicates_canonical
    2. Alias lookup in predicate_aliases
    3. Embedding similarity (ANN cosine on predicates_canonical.embedding)
    """
    if "\x00" in predicate or "\x00" in subject_type or "\x00" in object_type:
        raise HTTPException(400, "parameters cannot contain null bytes")
    lexeme = predicate.strip().lower().replace(" ", "_").replace("-", "_")
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Stage 1: exact match
        row = await conn.fetchrow(
            "SELECT name FROM predicates_canonical WHERE name = $1 AND state IN ('approved','experimental','candidate')",
            lexeme,
        )
        if row:
            return PredicateResolveResponse(canonical=row["name"], confidence=1.0, method="exact", original=predicate)

        # Stage 2: alias lookup
        alias_row = await conn.fetchrow(
            """SELECT canonical FROM predicate_aliases
               WHERE alias = $1 AND (domain = '' OR domain = $2 OR domain = $3)
               ORDER BY CASE WHEN domain = '' THEN 1 ELSE 0 END
               LIMIT 1""",
            lexeme, subject_type, object_type,
        )
        if alias_row:
            return PredicateResolveResponse(canonical=alias_row["canonical"], confidence=1.0, method="alias", original=predicate)

        # Stage 3: embedding similarity
        # Get embedding for the input predicate
        from embeddings_client import embed_text
        try:
            embedding_str = await embed_text(lexeme, prompt_name="query")
        except Exception:
            return PredicateResolveResponse(canonical=None, confidence=0.0, method="embedding_failed", original=predicate)

        # Parse embedding vector
        import json as _json
        vec = _json.loads(embedding_str) if isinstance(embedding_str, str) else embedding_str

        # ANN search against predicates_canonical embeddings
        best = await conn.fetchrow(
            """SELECT name, 1 - (embedding <=> $1::vector) AS similarity
               FROM predicates_canonical
               WHERE state IN ('approved','experimental','candidate')
                 AND embedding IS NOT NULL
               ORDER BY embedding <=> $1::vector
               LIMIT 1""",
            str(vec),
        )
        if best and best["similarity"] and float(best["similarity"]) > 0:
            # Type validation deferred — deuda Fase 3b

            return PredicateResolveResponse(
                canonical=best["name"],
                confidence=float(best["similarity"]),
                method="embedding",
                original=predicate,
            )

        return PredicateResolveResponse(canonical=None, confidence=0.0, method="none", original=predicate)


@router.get("/predicates/aliases", response_model=AliasListResponse)
async def list_aliases(actor: dict = Depends(get_current_user)) -> AliasListResponse:
    """List all predicate aliases for MCP cache."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT alias, canonical, domain FROM predicate_aliases ORDER BY alias")
    return AliasListResponse(aliases=[AliasEntry(alias=r["alias"], canonical=r["canonical"], domain=r["domain"]) for r in rows])


@router.get("/all")
async def get_full_graph(
    limit: int = Query(500, ge=1, le=5000, description="Max nodes to return"),
    offset: int = Query(0, ge=0, le=50000),
    actor: dict = Depends(get_current_user),
) -> dict:
    """Full graph — all active nodes + edges between them. Paginated, ordered by degree."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        node_rows = await conn.fetch("""
            WITH degree_counts AS (
                SELECT node_id, COUNT(*) AS degree FROM (
                    SELECT subject_id AS node_id FROM triples
                    UNION ALL
                    SELECT object_id FROM triples
                ) t GROUP BY node_id
            )
            SELECT n.id, n.name, n.type::text,
                   COALESCE(dc.degree, 0) AS degree
            FROM nodes n
            LEFT JOIN degree_counts dc ON dc.node_id = n.id
            WHERE n.status = 'active'
            ORDER BY COALESCE(dc.degree, 0) DESC, n.name
            LIMIT $1 OFFSET $2
        """, limit, offset)

        node_ids = [r["id"] for r in node_rows]
        edge_rows = await conn.fetch("""
            SELECT subject_id AS source, object_id AS target, predicate
            FROM triples
            WHERE subject_id = ANY($1::int[]) AND object_id = ANY($1::int[])
        """, node_ids) if node_ids else []

        cluster_info = {}
        cr_map: dict[int, int] = {}
        if node_ids:
            cluster_rows = await conn.fetch(
                "SELECT node_id, cluster_id FROM graph_clusters WHERE node_id = ANY($1::int[])",
                node_ids,
            )
            cr_map = {cr["node_id"]: cr["cluster_id"] for cr in cluster_rows}
            for cr in cluster_rows:
                cid = cr["cluster_id"]
                if cid not in cluster_info:
                    cluster_info[cid] = {"cluster_id": cid, "node_count": 0, "sample_nodes": []}
                cluster_info[cid]["node_count"] += 1
                if len(cluster_info[cid]["sample_nodes"]) < 3:
                    cluster_info[cid]["sample_nodes"].append(cr["node_id"])

    nodes = [{"id": r["id"], "name": r["name"], "type": r["type"], "degree": r["degree"]} for r in node_rows]
    for n in nodes:
        if n["id"] in cr_map:
            n["cluster_id"] = cr_map[n["id"]]

    seen_edges: set[tuple] = set()
    edges = []
    for r in edge_rows:
        key = (r["source"], r["target"], r["predicate"])
        if key not in seen_edges:
            seen_edges.add(key)
            edges.append({"source": r["source"], "target": r["target"], "predicate": r["predicate"]})

    return {
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "limit": limit,
        "offset": offset,
        "clusters": list(cluster_info.values()),
    }


@router.get("/subgraph")
async def get_subgraph(
    center: str = Query(None, min_length=1, max_length=MAX_NODE_NAME_LEN),
    limit: int = Query(0, ge=0, le=5000, description="Max nodes. 0 = auto"),
    offset: int = Query(0, ge=0, le=50000),
    depth: int = Query(2, ge=1, le=3),
    actor: dict = Depends(get_current_user),
) -> dict:
    """Subgrafo centrado en un nodo, formato D3/Cytoscape.

    Retorna nodes (id, name, type, degree) y edges (source, target, predicate).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        center_row = await conn.fetchrow(
            "SELECT id, name, type::text FROM nodes WHERE lower(name) = lower($1) LIMIT 1", center
        )
        if center_row is None:
            suggestion = await conn.fetchval(
                "SELECT name FROM nodes WHERE name % $1 ORDER BY similarity(name, $1) DESC LIMIT 1", center
            )
            if suggestion:
                raise HTTPException(404, f"node '{center}' not found. Did you mean '{suggestion}'?")
            raise HTTPException(404, f"node '{center}' not found")

        params = json.dumps({"center_name": center, "depth": depth})

        # Cypher: traversal hasta depth hops desde center
        try:
            edge_rows = await conn.fetch(f"""
                SELECT * FROM cypher('{GRAPH_NAME}', $$
                    MATCH path = (c:Entity {{name: $center_name}})-[*1..{depth}]-(n:Entity)
                    UNWIND relationships(path) AS r
                    RETURN startNode(r).name AS src, endNode(r).name AS tgt, r.predicate AS pred
                $$, $1::agtype) AS (src agtype, tgt agtype, pred agtype)
            """, params)
        except Exception as _cypher_err:
            logging.getLogger("ecodb.graph").warning("subgraph Cypher failed: %r", _cypher_err)
            edge_rows = []

        # Collect all node names
        all_names: set[str] = {center}
        edges_raw = []
        for r in edge_rows:
            src = _strip_agtype(r["src"])
            tgt = _strip_agtype(r["tgt"])
            pred = _strip_agtype(r["pred"])
            all_names.add(src)
            all_names.add(tgt)
            edges_raw.append((src, tgt, pred))

        # Fetch SQL node data for all names (id, type, degree)
        node_rows = await conn.fetch("""
            WITH degree_counts AS (
                SELECT node_id, COUNT(*) AS degree FROM (
                    SELECT subject_id AS node_id FROM triples
                    UNION ALL
                    SELECT object_id FROM triples
                ) t GROUP BY node_id
            )
            SELECT n.id, n.name, n.type::text,
                   COALESCE(dc.degree, 0) AS degree
            FROM nodes n
            LEFT JOIN degree_counts dc ON dc.node_id = n.id
            WHERE n.name = ANY($1::text[])
        """, list(all_names))

    name_to_id = {r["name"]: r["id"] for r in node_rows}
    nodes = [
        {
            "id": r["id"],
            "name": r["name"],
            "type": r["type"],
            "degree": r["degree"],
        }
        for r in node_rows
    ]
    edges = []
    seen_edges: set[tuple] = set()
    for src, tgt, pred in edges_raw:
        src_id = name_to_id.get(src)
        tgt_id = name_to_id.get(tgt)
        if src_id and tgt_id:
            key = (src_id, tgt_id, pred)
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append({"source": src_id, "target": tgt_id, "predicate": pred})

    if len(nodes) > 400:
        top_nodes = sorted(nodes, key=lambda n: n["degree"], reverse=True)[:200]
        top_ids = {n["id"] for n in top_nodes}
        cluster_info = {}
        async with pool.acquire() as conn:
            cluster_rows = await conn.fetch(
                "SELECT node_id, cluster_id FROM graph_clusters WHERE node_id = ANY($1::int[])",
                [n["id"] for n in nodes],
            )
        cr_map = {cr["node_id"]: cr["cluster_id"] for cr in cluster_rows}
        for cr in cluster_rows:
            cid = cr["cluster_id"]
            if cr["node_id"] not in top_ids:
                continue
            if cid not in cluster_info:
                cluster_info[cid] = {"cluster_id": cid, "node_count": 0, "sample_nodes": []}
            cluster_info[cid]["node_count"] += 1
            if len(cluster_info[cid]["sample_nodes"]) < 3:
                cluster_info[cid]["sample_nodes"].append(cr["node_id"])
        for n in top_nodes:
            n["cluster_id"] = cr_map.get(n["id"])
        filtered_edges = [e for e in edges if e["source"] in top_ids and e["target"] in top_ids]
        return {
            "center": center, "depth": depth,
            "nodes": top_nodes, "edges": filtered_edges,
            "truncated": True, "total_nodes": len(nodes), "shown_nodes": len(top_nodes),
            "clusters": list(cluster_info.values()),
        }

    return {"center": center, "depth": depth, "nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# Fase 5 — Entity merge helpers (Tasks 5.10-5.11)
# ---------------------------------------------------------------------------

async def _resolve_canonical(conn, node_id: int) -> int:
    """Follow merged_into chain to canonical active node.

    Applies path compression: intermediate nodes get their merged_into
    updated to point directly to the canonical, keeping future lookups O(1).
    """
    path: list[int] = [node_id]
    current = node_id
    for _ in range(_MAX_MERGE_CHAIN_DEPTH):  # depth guard — prevents infinite loop on corrupt chains
        row = await conn.fetchrow(
            "SELECT merged_into FROM nodes WHERE id = $1", current
        )
        if row is None or row["merged_into"] is None:
            canonical = current
            break
        current = row["merged_into"]
        path.append(current)
    else:
        raise RuntimeError(f"Merge chain depth exceeded {_MAX_MERGE_CHAIN_DEPTH} for node {node_id}")
    # Compress: point all intermediate nodes directly to canonical
    for intermediate in path[:-1]:
        if intermediate != canonical:
            await conn.execute(
                "UPDATE nodes SET merged_into = $1 WHERE id = $2 AND (merged_into IS NULL OR merged_into != $1)",
                canonical, intermediate,
            )
    return canonical


async def merge_entities(
    source_id: int,
    target_id: int,
    merged_by: int,
    reason: Optional[str],
    pool_or_conn,
) -> dict:
    """Task 5.10 — Soft-merge source node into target.

    Resolves target to its canonical node (chain compression).
    Marks source status='merged', merged_into=canonical.
    Logs operation to entity_merge_log.
    Returns merge log info dict.
    Raises ValueError on bad input.
    pool_or_conn: accepts either a Pool (acquires conn) or an existing Connection.
    """
    async def _do_merge(conn):
        src = await conn.fetchrow("SELECT id, status FROM nodes WHERE id = $1", source_id)
        if src is None:
            raise ValueError(f"source node {source_id} not found")
        if src["status"] == "merged":
            raise ValueError(f"source node {source_id} is already merged")

        tgt = await conn.fetchrow("SELECT id FROM nodes WHERE id = $1", target_id)
        if tgt is None:
            raise ValueError(f"target node {target_id} not found")

        canonical_id = await _resolve_canonical(conn, target_id)
        if canonical_id == source_id:
            raise ValueError("merge would create a cycle")

        async with conn.transaction():
            await conn.execute(
                "UPDATE nodes SET status = 'merged', merged_into = $1 WHERE id = $2",
                canonical_id, source_id,
            )
            await conn.execute("DELETE FROM graph_clusters WHERE node_id = $1", source_id)
            log_row = await conn.fetchrow(
                """
                INSERT INTO entity_merge_log
                    (source_node_id, target_node_id, target_original_id, merged_by, reason)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id, merged_at
                """,
                source_id, canonical_id, target_id, merged_by, reason,
            )
        return {
            "merge_log_id": log_row["id"],
            "source_node_id": source_id,
            "canonical_node_id": canonical_id,
            "merged_at": log_row["merged_at"].isoformat(),
        }

    if hasattr(pool_or_conn, 'acquire'):
        async with pool_or_conn.acquire() as conn:
            return await _do_merge(conn)
    else:
        return await _do_merge(pool_or_conn)


async def undo_merge(source_node_id: int, pool) -> dict:
    """Task 5.11 — Revert the most recent active merge for source_node_id.

    SELECT FOR UPDATE inside transaction prevents concurrent undo double-execution.
    Raises ValueError if none found.
    Note: graph_clusters row is NOT restored — next Louvain cycle (hourly) re-clusters.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            log_row = await conn.fetchrow(
                """SELECT id, target_original_id FROM entity_merge_log
                   WHERE source_node_id = $1 AND undone_at IS NULL
                   ORDER BY merged_at DESC LIMIT 1 FOR UPDATE""",
                source_node_id,
            )
            if log_row is None:
                raise ValueError(f"no active merge found for source node {source_node_id}")

            await conn.execute(
                "UPDATE nodes SET status = 'active', merged_into = NULL WHERE id = $1",
                source_node_id,
            )
            # Repoint nodes that were compressed through this source
            await conn.execute(
                "UPDATE nodes SET merged_into = $1 WHERE merged_into = $2 AND status = 'merged' AND id != $2",
                log_row["target_original_id"], source_node_id,
            )
            await conn.execute(
                "UPDATE entity_merge_log SET undone_at = now() WHERE id = $1",
                log_row["id"],
            )
    return {
        "merge_log_id": log_row["id"],
        "source_node_id": source_node_id,
        "status": "reverted",
    }


@router.get("/clusters")
async def get_graph_clusters(
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0, le=50000),
    actor: dict = Depends(get_current_user),
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT gc.node_id, n.name, gc.cluster_id, gc.computed_at
            FROM graph_clusters gc
            JOIN nodes n ON n.id = gc.node_id
            WHERE n.status = 'active'
            ORDER BY gc.cluster_id, n.name
            LIMIT $1 OFFSET $2
        """, limit, offset)
    grouped: dict[int, dict] = {}
    last_computed = None
    for r in rows:
        cid = r["cluster_id"]
        if cid not in grouped:
            grouped[cid] = {"cluster_id": cid, "node_count": 0, "nodes": []}
        grouped[cid]["node_count"] += 1
        grouped[cid]["nodes"].append({"node_id": r["node_id"], "name": r["name"]})
        if last_computed is None or r["computed_at"] > last_computed:
            last_computed = r["computed_at"]
    return {
        "clusters": list(grouped.values()),
        "cluster_count": len(grouped),
        "total_nodes": len(rows),
        "last_computed": last_computed.isoformat() if last_computed else None,
    }


@router.get("/triples/review")
async def list_needs_review(
    limit: int = Query(50, ge=1, le=200),
    actor: dict = Depends(get_current_user),
) -> dict:
    """List triples pending human review. KnowTwin schema has no needs_review column — returns empty."""
    return {"items": [], "count": 0}
