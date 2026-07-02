"""Background intelligence tasks — Fase 5 gobernanza cognitiva.

Runs hourly in the worker process via asyncio. Tasks execute sequentially
(serialized with ingesta via the worker's main loop).
"""
import json
import logging
from datetime import datetime, timezone

log = logging.getLogger("ecodb.background")


async def run_governance_cycle(pool) -> None:
    """Execute full governance cycle. Called hourly by worker."""
    log.info("Governance cycle starting")
    t0 = datetime.now(timezone.utc)
    # flush_accessed_buffer removed (D-P1.16-2): search.py queries dropped memories table
    for task_fn in (
        mark_stale_memories,
        purge_old_alias_candidates,
        purge_old_related_documents,
        reconcile_document_entities,
        reconcile_merged_entity_links,
        detect_tensions,
        update_corpus_vocabulary,
        update_graph_clusters,
    ):
        try:
            await task_fn(pool)
        except Exception as exc:
            log.error("Governance task %s failed: %r", task_fn.__name__, exc)
    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    log.info("Governance cycle complete in %.1fs", elapsed)


async def mark_stale_memories(pool) -> None:
    """Transition memories: active→stale, stale→dormant.

    Rules:
    - active→stale: decay makes freshness<0.3 AND last_accessed>60d ago (or never)
    - stale→dormant: last_accessed>90d ago (or never accessed + created>90d)
    - decision/acuerdo: NEVER auto-stale
    """
    async with pool.acquire() as conn:
        # active → stale
        staled = await conn.execute("""
            UPDATE memories SET staleness = 'stale', updated_at = now()
            WHERE staleness = 'active'
              AND type NOT IN ('decision', 'acuerdo')
              AND (last_accessed IS NULL OR last_accessed < now() - INTERVAL '60 days')
              AND created_at < now() - INTERVAL '60 days'
        """)
        # stale → dormant
        dormanted = await conn.execute("""
            UPDATE memories SET staleness = 'dormant', updated_at = now()
            WHERE staleness = 'stale'
              AND (last_accessed IS NULL OR last_accessed < now() - INTERVAL '90 days')
        """)
        log.info("Stale marking: %s→stale, %s→dormant", staled, dormanted)


async def purge_old_alias_candidates(pool) -> None:
    """Archive pending alias candidates older than 90 days. Max 500."""
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE entity_alias_candidates SET status = 'archived'
            WHERE id IN (
                SELECT id FROM entity_alias_candidates
                WHERE status = 'pending' AND first_seen < now() - INTERVAL '90 days'
                LIMIT 500
            )
        """)
        log.info("Alias candidates archived: %s", result)


async def purge_old_related_documents(pool) -> None:
    """Delete unconfirmed related_documents older than 90 days, archiving to trash."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            archived = await conn.fetch("""
                DELETE FROM related_documents
                WHERE ctid IN (
                    SELECT ctid FROM related_documents
                    WHERE confirmed_by IS NULL AND detected_at < now() - INTERVAL '90 days'
                    LIMIT 500
                )
                RETURNING source_id, target_id, relation_type, similarity, detected_at
            """)
            for row in archived:
                await conn.execute(
                    "INSERT INTO trash (id, original_table, original_data, deleted_at) VALUES (gen_random_uuid(), 'related_documents', $1::jsonb, now())",
                    json.dumps({
                        "source_id": str(row["source_id"]),
                        "target_id": str(row["target_id"]),
                        "relation_type": row["relation_type"],
                        "similarity": row["similarity"],
                        "detected_at": row["detected_at"].isoformat() if row["detected_at"] else None,
                    }),
                )
        log.info("Related documents purged: %d (archived to trash)", len(archived))


async def reconcile_document_entities(pool) -> None:
    """Task 5.13 — Find co-located similar entity pairs within documents.

    For each recently-indexed document, compares embedded entity pairs
    (cosine > 0.90) and records alias candidates. Up to 10 docs per cycle.
    Idempotent: uses SELECT + conditional insert on alias candidates.
    """
    async with pool.acquire() as conn:
        docs = await conn.fetch(
            """SELECT id FROM documents
               WHERE reconciled = false AND status = 'indexed'
               LIMIT 10"""
        )
        for doc in docs:
            try:
                pairs = await conn.fetch("""
                    SELECT del1.entity_node_id AS e1, del2.entity_node_id AS e2,
                           1 - (n1.embedding <=> n2.embedding) AS sim,
                           n2.name AS e2_name
                    FROM document_entity_links del1
                    JOIN document_entity_links del2
                         ON del1.document_id = del2.document_id
                        AND del1.entity_node_id < del2.entity_node_id
                    JOIN nodes n1 ON n1.id = del1.entity_node_id
                    JOIN nodes n2 ON n2.id = del2.entity_node_id
                    WHERE del1.document_id = $1
                      AND n1.embedding IS NOT NULL AND n2.embedding IS NOT NULL
                      AND 1 - (n1.embedding <=> n2.embedding) > 0.90
                      AND n1.status = 'active' AND n2.status = 'active'
                """, doc["id"])
                for pair in pairs:
                    existing = await conn.fetchrow(
                        """SELECT id, status FROM entity_alias_candidates
                           WHERE source_name = $1 AND target_node_id = $2
                             AND status IN ('pending', 'rejected')""",
                        pair["e2_name"], pair["e1"],
                    )
                    if existing:
                        await conn.execute(
                            """UPDATE entity_alias_candidates
                               SET occurrences = occurrences + 1,
                                   confidence = GREATEST(confidence, $2),
                                   last_seen = now()
                               WHERE id = $1""",
                            existing["id"], float(pair["sim"]),
                        )
                    elif existing is None:
                        await conn.execute(
                            """INSERT INTO entity_alias_candidates
                                   (source_name, target_node_id, confidence, occurrences, sample_contexts)
                               VALUES ($1, $2, $3, 1, ARRAY[$4]::text[])""",
                            pair["e2_name"], pair["e1"], float(pair["sim"]),
                            f"reconcile:{doc['id']}",
                        )
                await conn.execute(
                    "UPDATE documents SET reconciled = true WHERE id = $1", doc["id"]
                )
            except Exception as exc:
                log.warning("reconcile_document_entities doc=%s failed: %r", doc["id"], exc)


async def reconcile_merged_entity_links(pool) -> None:
    """Task 5.13 — Reroute entity links pointing to merged nodes to their canonical.

    Handles memory_entity_links and document_entity_links. Up to 500 each per cycle.
    For each stale link: delete old, insert pointing to canonical (ON CONFLICT DO NOTHING
    handles already-linked cases). Best-effort per row.
    """
    async with pool.acquire() as conn:
        mem_rows = await conn.fetch("""
            SELECT mel.memory_id, mel.entity_node_id AS old_id, n.merged_into AS new_id
            FROM memory_entity_links mel
            JOIN nodes n ON n.id = mel.entity_node_id
            WHERE n.status = 'merged' AND n.merged_into IS NOT NULL
            LIMIT 500
        """)
        mem_fixed = 0
        for r in mem_rows:
            try:
                async with conn.transaction():
                    await conn.execute(
                        "DELETE FROM memory_entity_links WHERE memory_id = $1 AND entity_node_id = $2",
                        r["memory_id"], r["old_id"],
                    )
                    await conn.execute(
                        """INSERT INTO memory_entity_links (memory_id, entity_node_id)
                           VALUES ($1, $2) ON CONFLICT DO NOTHING""",
                        r["memory_id"], r["new_id"],
                    )
                    mem_fixed += 1
            except Exception as exc:
                log.warning("reconcile memory link failed mem=%s old=%s: %r", r["memory_id"], r["old_id"], exc)

        doc_rows = await conn.fetch("""
            SELECT del.document_id, del.entity_node_id AS old_id, del.chunk_id, n.merged_into AS new_id
            FROM document_entity_links del
            JOIN nodes n ON n.id = del.entity_node_id
            WHERE n.status = 'merged' AND n.merged_into IS NOT NULL
            LIMIT 500
        """)
        doc_fixed = 0
        for r in doc_rows:
            try:
                async with conn.transaction():
                    await conn.execute(
                        "DELETE FROM document_entity_links WHERE document_id = $1 AND entity_node_id = $2 AND chunk_id IS NOT DISTINCT FROM $3",
                        r["document_id"], r["old_id"], r["chunk_id"],
                    )
                    await conn.execute(
                        """INSERT INTO document_entity_links (document_id, entity_node_id, chunk_id)
                           VALUES ($1, $2, $3) ON CONFLICT DO NOTHING""",
                        r["document_id"], r["new_id"], r["chunk_id"],
                    )
                    doc_fixed += 1
            except Exception as exc:
                log.warning("reconcile doc link failed doc=%s old=%s: %r", r["document_id"], r["old_id"], exc)

        log.info("Reconcile entity links: mem_fixed=%d doc_fixed=%d", mem_fixed, doc_fixed)


async def update_corpus_vocabulary(pool) -> None:
    """Fase B.3 — Extract unique terms from recent memories and embed for BM25 expansion."""
    from settings import ENABLE_BM25_EXPANSION
    if not ENABLE_BM25_EXPANSION:
        return
    async with pool.acquire() as conn:
        rows = await conn.fetch(r"""
            SELECT DISTINCT unnest(
                regexp_split_to_array(lower(content), '\s+')
            ) AS term
            FROM memories
            WHERE created_at > now() - INTERVAL '7 days'
              AND (staleness IS NULL OR staleness NOT IN ('dormant', 'archived'))
            LIMIT 500
        """)
        new_terms = [r["term"] for r in rows
                     if len(r["term"]) >= 4 and r["term"].isalpha()]

        existing = await conn.fetch(
            "SELECT term FROM corpus_vocabulary WHERE term = ANY($1::text[])",
            new_terms)
        existing_set = {r["term"] for r in existing}
        to_embed = [t for t in new_terms if t not in existing_set][:50]

        if not to_embed:
            return

        from embeddings_client import embed_text
        added = 0
        for term in to_embed:
            try:
                emb = await embed_text(term)
                await conn.execute(
                    "INSERT INTO corpus_vocabulary (term, embedding) VALUES ($1, $2::vector) "
                    "ON CONFLICT (term) DO NOTHING",
                    term, emb)
                added += 1
            except Exception as e:
                log.debug("embed term %s failed: %r", term, e)
                continue

        log.info("Corpus vocabulary: added %d terms", added)


async def detect_tensions(pool) -> None:
    """Task 5.19 — Detect semantic tensions between recent memories and document chunks.

    Finds memories and document chunks sharing ≥2 entities where cosine sim > 0.85
    (indicating contradiction candidates). Broadcasts tension_detected SSE event.
    No-op when ENABLE_TENSION_DETECTION is False.
    """
    from settings import ENABLE_TENSION_DETECTION
    if not ENABLE_TENSION_DETECTION:
        return
    async with pool.acquire() as conn:
        tensions = await conn.fetch("""
            WITH recent_memories AS (
                SELECT m.id AS memory_id, array_agg(DISTINCT mel.entity_node_id) AS entity_ids
                FROM memories m
                JOIN memory_entity_links mel ON mel.memory_id = m.id
                WHERE m.created_at > now() - INTERVAL '7 days'
                  AND m.staleness = 'active'
                GROUP BY m.id
                HAVING count(DISTINCT mel.entity_node_id) >= 2
                LIMIT 50
            ),
            candidate_chunks AS (
                SELECT rm.memory_id, dc.id AS chunk_id,
                       count(DISTINCT del.entity_node_id) AS shared_entities
                FROM recent_memories rm
                JOIN document_entity_links del ON del.entity_node_id = ANY(rm.entity_ids)
                JOIN document_chunks dc ON dc.id = del.chunk_id
                WHERE dc.embedding IS NOT NULL
                GROUP BY rm.memory_id, dc.id
                HAVING count(DISTINCT del.entity_node_id) >= 2
            ),
            tension_scores AS (
                SELECT cc.memory_id, cc.chunk_id,
                       1 - (me.embedding <=> dc.embedding) AS cosine
                FROM candidate_chunks cc
                JOIN memory_embeddings me ON me.memory_id = cc.memory_id AND me.modality = 'text'
                JOIN document_chunks dc ON dc.id = cc.chunk_id
                WHERE 1 - (me.embedding <=> dc.embedding) > 0.85
            )
            SELECT count(*) AS tension_count FROM tension_scores
        """)
        count = tensions[0]["tension_count"] if tensions else 0
        if count > 0:
            from events import broadcast_event
            await broadcast_event("tension_detected", {"count": count}, org_id=None)
            log.info("Tensions detected: %d", count)


async def update_graph_clusters(pool) -> None:
    """Compute Louvain community detection on the graph and write to graph_clusters.

    Reads triples → builds networkx graph → runs Louvain → upserts results.
    Timeout: 120s. Skips if graph has <10 nodes.
    """
    import asyncio
    import os
    min_degree = int(os.getenv("LOUVAIN_MIN_DEGREE", "2"))

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name FROM nodes WHERE status = 'active'"
        )
        if len(rows) < 10:
            log.info("update_graph_clusters: skipped, only %d active nodes", len(rows))
            return

        if min_degree > 1:
            triples = await conn.fetch("""
                WITH active_edges AS (
                    SELECT t.subject_id, t.object_id
                    FROM triples t
                    JOIN nodes n1 ON t.subject_id = n1.id AND n1.status = 'active'
                    JOIN nodes n2 ON t.object_id = n2.id AND n2.status = 'active'
                ),
                node_degrees AS (
                    SELECT node_id, count(*) AS degree FROM (
                        SELECT subject_id AS node_id FROM active_edges
                        UNION ALL
                        SELECT object_id AS node_id FROM active_edges
                    ) d GROUP BY node_id HAVING count(*) >= $1
                )
                SELECT ae.subject_id, ae.object_id
                FROM active_edges ae
                WHERE ae.subject_id IN (SELECT node_id FROM node_degrees)
                  AND ae.object_id IN (SELECT node_id FROM node_degrees)
            """, min_degree)
        else:
            triples = await conn.fetch("""
                SELECT t.subject_id, t.object_id
                FROM triples t
                JOIN nodes n1 ON t.subject_id = n1.id AND n1.status = 'active'
                JOIN nodes n2 ON t.object_id = n2.id AND n2.status = 'active'
            """)

    import networkx as nx
    from networkx.algorithms.community import louvain_communities

    G = nx.Graph()
    for t in triples:
        G.add_edge(t["subject_id"], t["object_id"])

    try:
        communities = await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(
                None, lambda: louvain_communities(G, seed=42)
            ),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        log.warning("update_graph_clusters: Louvain timed out after 120s")
        return

    cluster_rows = []
    for cluster_id, members in enumerate(communities):
        for node_id in members:
            cluster_rows.append((node_id, cluster_id))

    if not cluster_rows:
        log.warning("update_graph_clusters: 0 clusters computed — skipping write to preserve existing data")
        return

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM graph_clusters")
            await conn.executemany(
                "INSERT INTO graph_clusters (node_id, cluster_id, computed_at) VALUES ($1, $2, now())",
                cluster_rows,
            )
    log.info("update_graph_clusters: %d nodes → %d clusters", len(cluster_rows), len(communities))
