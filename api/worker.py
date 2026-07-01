"""EcoDB document ingestion worker — Fase 4 Task 4.1.

Standalone process. Listens for NOTIFY on channel 'ecodb_ingest'.
Processes documents: parse → chunk → GLiNER → embed → graph link.
Entrypoint: python worker.py
Docker: docker compose --profile with-ingestion up
"""
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import time

import asyncpg
import httpx

from background import run_governance_cycle

log = logging.getLogger("ecodb.worker")

DATABASE_URL = os.environ["DATABASE_URL"]
from settings import EMBEDDINGS_URL
API_URL = os.environ.get("ECODB_API_INTERNAL_URL", "http://ecodb-api:8080")
MEDIA_STORE_DIR = os.environ.get("MEDIA_STORE_DIR", "/app/media")

_URL_SCHEME_RE = re.compile(r'^(https?|ftp|file|rtsp|rtmp)://', re.IGNORECASE)


def _extract_frontmatter_tags(text: str) -> list[str]:
    """Extract tags list from YAML frontmatter (---...---) at top of text."""
    match = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    if not match:
        return []
    try:
        import yaml
        fm = yaml.safe_load(match.group(1))
        if not isinstance(fm, dict):
            return []
        tags = fm.get("tags", [])
        return [str(t) for t in tags] if isinstance(tags, list) else []
    except Exception:
        return []

# Timeouts per stage (seconds)
PARSE_TIMEOUT = int(os.environ.get("PARSE_TIMEOUT", "300"))
EMBED_TIMEOUT = int(os.environ.get("EMBED_TIMEOUT", "120"))
GLINER_TIMEOUT = int(os.environ.get("GLINER_TIMEOUT", "60"))
WHISPER_TIMEOUT = int(os.environ.get("WHISPER_TIMEOUT", "1800"))

# Circuit breaker for embeddings
from settings import CB_THRESHOLD, CB_WINDOW, CB_COOLDOWN
_cb_failures: list[float] = []
_cb_open_until: float = 0.0


class EmbeddingsServiceError(RuntimeError):
    pass

# Recovery
RECOVERY_INTERVAL = 300          # 5 min
RECOVERY_STALE_THRESHOLD = 600   # 10 min
MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Path validation (B1-1 LFI/SSRF guard)
# ---------------------------------------------------------------------------

def _validate_document_path(uri: str) -> str:
    """Validate uri is a real file within allowed base dir. Raises ValueError on violation."""
    if _URL_SCHEME_RE.match(uri):
        raise ValueError(f"URL schemes not allowed in document URI: {uri[:50]}")
    real = Path(os.path.realpath(uri))
    allowed = Path(os.path.realpath(MEDIA_STORE_DIR))
    if not real.is_relative_to(allowed):
        raise ValueError(f"Document path outside media store: {uri[:50]}")
    if not real.is_file():
        raise ValueError(f"Document file not found: {uri[:50]}")
    return str(real)


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

def _circuit_breaker_ok() -> bool:
    now = time.time()
    if now < _cb_open_until:
        return False
    _cb_failures[:] = [t for t in _cb_failures if now - t < CB_WINDOW]
    return len(_cb_failures) < CB_THRESHOLD


def _circuit_breaker_record_failure() -> None:
    global _cb_open_until
    now = time.time()
    _cb_failures.append(now)
    recent = [t for t in _cb_failures if now - t < CB_WINDOW]
    if len(recent) >= CB_THRESHOLD:
        _cb_open_until = now + CB_COOLDOWN
        log.warning(
            "Circuit breaker OPEN — embeddings failures >= %d in %ds. Cooling %ds.",
            CB_THRESHOLD, CB_WINDOW, CB_COOLDOWN,
        )


# ---------------------------------------------------------------------------
# SSE broadcast (Task 4.13)
# ---------------------------------------------------------------------------

_INTERNAL_SECRET = os.environ.get("INTERNAL_BROADCAST_SECRET", "")


async def _broadcast_sse(event_type: str, data: dict, org_id: int | None = None) -> None:
    """Best-effort SSE broadcast via internal API. Never raises."""
    try:
        headers = {}
        if _INTERNAL_SECRET:
            headers["X-Internal-Secret"] = _INTERNAL_SECRET
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{API_URL}/api/v1/events/broadcast",
                json={"event_type": event_type, "data": data, "org_id": org_id},
                headers=headers,
            )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Document pipeline
# ---------------------------------------------------------------------------

async def process_document(pool: asyncpg.Pool, document_id: str) -> None:
    """Main pipeline: parse → chunk → embed → GLiNER → graph link."""
    t0 = time.time()
    metrics: dict = {}

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE documents
            SET status = 'processing', processing_started_at = now()
            WHERE id = $1 AND status = 'queued'
            RETURNING id, uri, filename, doc_type, workspace_id, project_id, visibility
            """,
            document_id,
        )
        if row is None:
            log.debug("Document %s already claimed or not queued, skipping.", document_id)
            return

    doc_id = row["id"]
    doc_type = row["doc_type"]
    uri = row["uri"]

    _doc_org_id: int | None = None
    try:
        async with pool.acquire() as conn:
            from events import resolve_org_id_from_project
            _doc_org_id = await resolve_org_id_from_project(conn, row["project_id"])
    except Exception:
        pass

    # Translate Windows media path to Docker mount path
    _WIN_MEDIA = os.environ.get("WINDOWS_MEDIA_PREFIX", "")
    if _WIN_MEDIA:
        _win_fwd = _WIN_MEDIA.replace("\\", "/")
        if uri.startswith(_WIN_MEDIA):
            uri = uri.replace(_WIN_MEDIA, MEDIA_STORE_DIR).replace("\\", "/")
        elif uri.startswith(_win_fwd):
            uri = uri.replace(_win_fwd, MEDIA_STORE_DIR)

    try:
        safe_path = _validate_document_path(uri)

        # Re-index: clear old chunks if present (Task 4.13 Part A)
        linked_memory_ids: list[str] = []
        async with pool.acquire() as conn:
            existing_chunks = await conn.fetchval(
                "SELECT count(*) FROM document_chunks WHERE document_id = $1", doc_id
            )
            if existing_chunks > 0:
                await conn.execute(
                    "DELETE FROM document_chunks WHERE document_id = $1", doc_id
                )
                log.info("Re-index: deleted %d old chunks for %s", existing_chunks, doc_id)
                # Task 5.16 — Increment document_version on re-index
                await conn.execute(
                    "UPDATE documents SET document_version = document_version + 1 WHERE id = $1",
                    doc_id,
                )
                # Collect linked memories for source_updated broadcast after success
                linked_rows = await conn.fetch(
                    "SELECT memory_id FROM memory_document_links WHERE document_id = $1", doc_id
                )
                linked_memory_ids = [str(r["memory_id"]) for r in linked_rows]

        # Stage 1: Parse (Task 4.2 Docling / Task 4.3 Whisper)
        from parsers import AUDIO_EXTENSIONS, parse_document, transcribe_audio
        t_parse = time.time()
        file_ext = os.path.splitext(safe_path)[1].lower()
        if file_ext in AUDIO_EXTENSIONS:
            parse_result = await asyncio.wait_for(
                transcribe_audio(safe_path), timeout=WHISPER_TIMEOUT
            )
            metrics["parser"] = "whisper"
        else:
            parse_result = await asyncio.wait_for(
                parse_document(safe_path, doc_type), timeout=PARSE_TIMEOUT
            )
            metrics["parser"] = "docling"
        metrics["parse_ms"] = round((time.time() - t_parse) * 1000)

        # SHA-256 of raw file (Task 4.13 Part A) + Task 5.15 deduplication
        file_hash = None
        content_fingerprint = None
        try:
            with open(safe_path, "rb") as _f:
                file_bytes = _f.read()
            file_hash = hashlib.sha256(file_bytes).hexdigest()

            # Normalized text fingerprint (same content, different format → near-dup)
            _parsed_text = ""
            try:
                _parsed_text = parse_result.get("text", "") if isinstance(parse_result, dict) else str(parse_result)
            except Exception:
                pass
            _normalized = re.sub(r"[^\w\s]", "", _parsed_text.lower())
            _normalized = re.sub(r"\s+", " ", _normalized).strip()
            content_fingerprint = hashlib.sha256(_normalized.encode()).hexdigest() if _normalized else None

            async with pool.acquire() as conn:
                # Exact duplicate check (same raw file)
                dup_exact = await conn.fetchrow(
                    "SELECT id FROM documents WHERE file_hash = $1 AND id != $2 AND status != 'deleted'",
                    file_hash, doc_id,
                )
                if dup_exact:
                    log.info("Document %s is exact duplicate of %s — skipping", doc_id, dup_exact["id"])
                    await conn.execute(
                        "UPDATE documents SET status = 'failed', processing_metrics = $1 WHERE id = $2",
                        json.dumps({"reason": "duplicate", "duplicate_of": str(dup_exact["id"])}),
                        doc_id,
                    )
                    await _broadcast_sse("duplicate_detected", {
                        "document_id": str(doc_id),
                        "duplicate_of": str(dup_exact["id"]),
                        "match": "exact",
                    }, _doc_org_id)
                    return

                await conn.execute(
                    "UPDATE documents SET file_hash = $1, content_fingerprint = $2 WHERE id = $3",
                    file_hash, content_fingerprint, doc_id,
                )
        except Exception as _fh_exc:
            log.debug("file_hash/fingerprint update skipped: %r", _fh_exc)

        # Extract frontmatter tags from parsed text (propagated to all chunks)
        _parsed_text_for_tags = ""
        try:
            _parsed_text_for_tags = parse_result.get("text", "") if isinstance(parse_result, dict) else str(parse_result)
        except Exception:
            pass
        doc_tags = _extract_frontmatter_tags(_parsed_text_for_tags)

        # Stage 2: Chunk
        t_chunk = time.time()
        from chunker import chunk_document
        chunks = chunk_document(parse_result, doc_type)
        async with pool.acquire() as conn:
            for chunk in chunks:
                await conn.execute(
                    "INSERT INTO document_chunks"
                    " (document_id, chunk_index, content, section_path, metadata, tags)"
                    " VALUES ($1, $2, $3, $4, $5::jsonb, $6::text[])",
                    doc_id, chunk.chunk_index, chunk.content,
                    chunk.section_path, json.dumps(chunk.metadata), doc_tags,
                )
        metrics["chunk_count"] = len(chunks)
        metrics["chunk_ms"] = round((time.time() - t_chunk) * 1000)

        # Stage 3: GLiNER entity extraction
        t_gliner = time.time()
        from gliner_service import extract_entities_from_chunks
        entity_results = await asyncio.wait_for(
            extract_entities_from_chunks(chunks, pool), timeout=GLINER_TIMEOUT
        )
        metrics["gliner_entity_count"] = sum(len(r["entities"]) for r in entity_results)
        metrics["gliner_ms"] = round((time.time() - t_gliner) * 1000)

        # Stage 4: Embed chunks
        t_embed = time.time()
        if not _circuit_breaker_ok():
            raise RuntimeError("Embeddings circuit breaker OPEN")
        batch_size = int(os.environ.get("EMBED_BATCH_SIZE", "16"))
        async with httpx.AsyncClient(timeout=float(EMBED_TIMEOUT)) as client:
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i:i + batch_size]
                texts = [c.content for c in batch]
                resp = await client.post(
                    f"{EMBEDDINGS_URL}/embed/text",
                    json={
                        "texts": texts,
                        "task": "retrieval",
                        "prompt_name": "passage",
                        "truncate_dim": 512,
                    },
                )
                if resp.status_code != 200:
                    raise EmbeddingsServiceError(f"Embeddings service returned {resp.status_code}")
                embeddings = resp.json()["embeddings"]
                async with pool.acquire() as conn:
                    for j, emb in enumerate(embeddings):
                        chunk_idx = chunks[i + j].chunk_index
                        emb_literal = "[" + ",".join(str(x) for x in emb) + "]"
                        await conn.execute(
                            "UPDATE document_chunks SET embedding = $1::vector"
                            " WHERE document_id = $2 AND chunk_index = $3",
                            emb_literal, doc_id, chunk_idx,
                        )
        metrics["embed_ms"] = round((time.time() - t_embed) * 1000)

        # Stage 5: Graph entity linking
        t_graph = time.time()
        from graph import _ensure_node
        entity_link_count = 0
        async with pool.acquire() as conn:
            chunk_id_rows = await conn.fetch(
                "SELECT chunk_index, id FROM document_chunks WHERE document_id = $1",
                doc_id,
            )
            chunk_id_map = {r["chunk_index"]: r["id"] for r in chunk_id_rows}
            for er in entity_results:
                chunk_idx = er["chunk_index"]
                chunk_id = chunk_id_map.get(chunk_idx)
                if chunk_id is None:
                    continue
                for entity in er["entities"]:
                    try:
                        async with conn.transaction():
                            node_sql_id = await _ensure_node(conn, entity["text"])
                            await conn.execute(
                                """
                                INSERT INTO document_entity_links (document_id, entity_node_id, chunk_id)
                                VALUES ($1, $2, $3)
                                ON CONFLICT (document_id, entity_node_id, chunk_id) DO NOTHING
                                """,
                                doc_id, node_sql_id, chunk_id,
                            )
                            entity_link_count += 1
                    except Exception as exc:
                        log.warning("Entity link failed for %s/%s: %r", entity["text"], chunk_idx, exc)
        metrics["entity_link_count"] = entity_link_count
        metrics["graph_ms"] = round((time.time() - t_graph) * 1000)

        # Chunking strategy breakdown
        structured_count = sum(1 for c in chunks if c.section_path is not None)
        fallback_count = len(chunks) - structured_count
        metrics["chunking_strategy_breakdown"] = {
            "structured_chunk_pct": round(structured_count / max(len(chunks), 1) * 100, 1),
            "fallback_chunk_pct": round(fallback_count / max(len(chunks), 1) * 100, 1),
        }

        # Success
        metrics["total_ms"] = round((time.time() - t0) * 1000)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE documents
                SET status = 'indexed',
                    last_indexed = now(),
                    processing_metrics = $2::jsonb
                WHERE id = $1
                """,
                doc_id, json.dumps(metrics),
            )

        # Task 5.15 — Near-duplicate check (same text, different file format)
        if content_fingerprint:
            try:
                async with pool.acquire() as conn:
                    near_dup = await conn.fetchrow(
                        "SELECT id FROM documents WHERE content_fingerprint = $1 AND id != $2 AND status = 'indexed'",
                        content_fingerprint, doc_id,
                    )
                    if near_dup:
                        await conn.execute(
                            """INSERT INTO related_documents (source_id, target_id, relation_type, similarity)
                               VALUES ($1, $2, 'near_duplicate', 1.0)
                               ON CONFLICT DO NOTHING""",
                            doc_id, near_dup["id"],
                        )
                        await _broadcast_sse("duplicate_detected", {
                            "document_id": str(doc_id),
                            "similar_to": str(near_dup["id"]),
                            "match": "normalized",
                        }, _doc_org_id)
            except Exception as _nd_exc:
                log.debug("near-dup check skipped: %r", _nd_exc)

        # SSE broadcasts (Task 4.13 Part B)
        await _broadcast_sse("document_indexed", {
            "document_id": str(doc_id),
            "chunks": metrics.get("chunk_count", 0),
        }, _doc_org_id)
        if linked_memory_ids:
            await _broadcast_sse("source_updated", {
                "document_id": str(doc_id),
                "affected_memory_ids": linked_memory_ids,
            }, _doc_org_id)

        log.info(
            "Document %s indexed in %dms (%d chunks)",
            doc_id, metrics["total_ms"], metrics.get("chunk_count", 0),
        )

    except Exception as exc:
        log.error("Document %s failed: %r", doc_id, exc)
        if isinstance(exc, EmbeddingsServiceError):
            _circuit_breaker_record_failure()

        async with pool.acquire() as conn:
            fail_row = await conn.fetchrow(
                """
                UPDATE documents
                SET status = CASE WHEN retry_count + 1 >= $2 THEN 'failed' ELSE 'queued' END,
                    retry_count = retry_count + 1,
                    processing_metrics = $3::jsonb,
                    processing_started_at = NULL
                WHERE id = $1
                RETURNING status
                """,
                doc_id,
                MAX_RETRIES,
                json.dumps({
                    **metrics,
                    "error": type(exc).__name__,
                    "error_detail": str(exc)[:200],
                }),
            )
        if fail_row and fail_row["status"] == "failed":
            await _broadcast_sse("document_failed", {
                "document_id": str(doc_id),
                "error": type(exc).__name__,
            }, _doc_org_id)


# ---------------------------------------------------------------------------
# Recovery helpers
# ---------------------------------------------------------------------------

async def recover_stuck_documents(pool: asyncpg.Pool, stuck_timeout_minutes: int = 30) -> int:
    """Reset documents stuck in 'processing' for longer than timeout.

    Runs at worker startup to recover from process crashes.
    """
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE documents
            SET status = 'queued',
                processing_started_at = NULL,
                retry_count = retry_count + 1
            WHERE status = 'processing'
              AND processing_started_at < now() - ($1 || ' minutes')::interval
              AND retry_count < $2
        """, str(stuck_timeout_minutes), MAX_RETRIES)
        count = int(result.split()[-1]) if result else 0
        if count > 0:
            log.info("Recovered %d stuck documents (processing > %d min)", count, stuck_timeout_minutes)
        await conn.execute("""
            UPDATE documents
            SET status = 'failed',
                processing_metrics = jsonb_build_object('error', 'WorkerCrash', 'error_detail', 'stuck in processing after worker restart')
            WHERE status = 'processing'
              AND processing_started_at < now() - ($1 || ' minutes')::interval
              AND retry_count >= $2
        """, str(stuck_timeout_minutes), MAX_RETRIES)
        return count


async def recovery_loop(pool: asyncpg.Pool) -> None:
    """Reset stale 'processing' documents back to 'queued'."""
    while True:
        await asyncio.sleep(RECOVERY_INTERVAL)
        try:
            async with pool.acquire() as conn:
                result = await conn.execute(
                    """
                    UPDATE documents
                    SET status = 'queued', processing_started_at = NULL
                    WHERE status = 'processing'
                      AND processing_started_at < now() - make_interval(secs => $1::float)
                      AND retry_count < $2
                    """,
                    float(RECOVERY_STALE_THRESHOLD),
                    MAX_RETRIES,
                )
                if result != "UPDATE 0":
                    log.warning("Recovery: reset stale documents: %s", result)
        except Exception as exc:
            log.error("Recovery loop error: %r", exc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    log.info("Worker starting. DATABASE_URL=%s...", DATABASE_URL[:30])

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)
    await recover_stuck_documents(pool)
    _recovery_task = asyncio.create_task(recovery_loop(pool))

    async def _governance_loop():
        try:
            await run_governance_cycle(pool)
        except Exception as exc:
            log.error("Initial governance cycle failed: %r", exc)
        while True:
            await asyncio.sleep(3600)
            try:
                await run_governance_cycle(pool)
            except Exception as exc:
                log.error("Governance cycle failed: %r", exc)

    _governance_task = asyncio.create_task(_governance_loop())

    async def _access_flush_loop():
        while True:
            await asyncio.sleep(300)
            try:
                from search import flush_accessed_buffer
                await flush_accessed_buffer(pool)
            except Exception as exc:
                log.error("Access flush failed: %r", exc)

    _access_flush_task = asyncio.create_task(_access_flush_loop())

    # asyncpg LISTEN/NOTIFY: callback-based API puts payloads into a queue.
    # conn.add_listener registers callback; the main loop awaits queue.get().
    notify_queue: asyncio.Queue[str] = asyncio.Queue()

    def _on_notify(connection: asyncpg.Connection, pid: int, channel: str, payload: str) -> None:
        notify_queue.put_nowait(payload)

    listen_conn = await asyncpg.connect(DATABASE_URL)
    await listen_conn.add_listener("ecodb_ingest", _on_notify)
    log.info("Worker listening on channel 'ecodb_ingest'")

    try:
        # Drain already-queued documents on startup
        async with pool.acquire() as conn:
            queued = await conn.fetch(
                "SELECT id FROM documents WHERE status = 'queued' ORDER BY created_at LIMIT 10"
            )
        for row in queued:
            await process_document(pool, str(row["id"]))

        # Main loop: block on notify queue, fall back to periodic poll on timeout
        while True:
            try:
                payload = await asyncio.wait_for(notify_queue.get(), timeout=30.0)
                if payload:
                    await process_document(pool, payload)
                else:
                    # Empty payload NOTIFY → drain queued
                    async with pool.acquire() as conn:
                        queued = await conn.fetch(
                            "SELECT id FROM documents WHERE status = 'queued' ORDER BY created_at LIMIT 5"
                        )
                    for row in queued:
                        await process_document(pool, str(row["id"]))
            except asyncio.TimeoutError:
                # Periodic poll fallback (guards against missed NOTIFYs)
                async with pool.acquire() as conn:
                    queued = await conn.fetch(
                        "SELECT id FROM documents WHERE status = 'queued' ORDER BY created_at LIMIT 5"
                    )
                for row in queued:
                    await process_document(pool, str(row["id"]))
            except Exception as exc:
                log.error("Main loop error: %r", exc)
                await asyncio.sleep(5)
    finally:
        await listen_conn.remove_listener("ecodb_ingest", _on_notify)
        await listen_conn.close()
        _recovery_task.cancel()
        _governance_task.cancel()
        _access_flush_task.cancel()
        try:
            await asyncio.gather(_recovery_task, _governance_task, _access_flush_task, return_exceptions=True)
        except Exception:
            pass
        await pool.close()
        log.info("Worker shutdown complete.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    asyncio.run(main())
