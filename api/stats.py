"""Endpoints de estadísticas — ."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import get_current_user
from db import get_pool
from permissions import visible_project_ids
from settings import EMBEDDINGS_URL

router = APIRouter(prefix="/stats", tags=["stats"])

_PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}
_EMBEDDINGS_URL = EMBEDDINGS_URL
_EMBEDDINGS_ALLOWED_FIELDS = {"model_loaded", "cpu_percent", "quantization"}


def _period_to_days(period: str) -> int:
    days = _PERIOD_DAYS.get(period)
    if days is None:
        raise HTTPException(422, f"invalid period '{period}'. Valid: {list(_PERIOD_DAYS)}")
    return days


# ---------------------------------------------------------------------------
# GET /stats/memories
# ---------------------------------------------------------------------------

@router.get("/memories")
async def stats_memories(
    workspace_id: Optional[int] = Query(None),
    period: str = Query("30d"),
    group_by: Literal["type", "project", "agent"] = Query("type"),
    actor: dict = Depends(get_current_user),
) -> dict:
    """Distribución de memorias por tipo/proyecto/agente en el período."""
    days = _period_to_days(period)
    is_super = bool(actor.get("is_super"))
    pool = await get_pool()

    async with pool.acquire() as conn:
        if is_super:
            project_filter = ""
            params: list = [days]
        else:
            visible = await visible_project_ids(conn, actor)
            if not visible:
                return {"period": period, "group_by": group_by, "data": [], "total": 0}
            project_filter = "AND m.project_id = ANY($2::int[])"
            params = [days, list(visible)]

        if workspace_id is not None:
            params.append(workspace_id)
            ws_idx = len(params)
            project_filter += f" AND m.workspace_id = ${ws_idx}"

        if group_by == "type":
            label_expr = "m.type::text"
            join_clause = ""
        elif group_by == "project":
            label_expr = "p.name"
            join_clause = "JOIN projects p ON p.id = m.project_id"
        else:  # agent
            label_expr = "COALESCE(a.identifier, 'user')"
            join_clause = "LEFT JOIN agents a ON a.id = m.agent_id"

        sql = f"""
            SELECT {label_expr} AS label, COUNT(*) AS count
            FROM memories m
            {join_clause}
            WHERE m.created_at >= NOW() - make_interval(days => $1)
            {project_filter}
            GROUP BY {label_expr}
            ORDER BY count DESC
        """
        rows = await conn.fetch(sql, *params)

    data = [{"label": r["label"], "count": r["count"]} for r in rows]
    total = sum(r["count"] for r in data)
    return {"period": period, "group_by": group_by, "data": data, "total": total}


# ---------------------------------------------------------------------------
# GET /stats/graph
# ---------------------------------------------------------------------------

@router.get("/graph")
async def stats_graph(actor: dict = Depends(get_current_user)) -> dict:
    """Totales y crecimiento diario de nodos y tripletas (últimos 30 días)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        nodes_total = await conn.fetchval("SELECT COUNT(*) FROM nodes")
        triples_total = await conn.fetchval("SELECT COUNT(*) FROM triples")

        daily_nodes = await conn.fetch("""
            SELECT DATE(created_at) AS day, COUNT(*) AS cnt
            FROM nodes
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY day ORDER BY day
        """)
        daily_triples = await conn.fetch("""
            SELECT DATE(created_at) AS day, COUNT(*) AS cnt
            FROM triples
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY day ORDER BY day
        """)

    # Merge into unified daily list
    node_map = {str(r["day"]): r["cnt"] for r in daily_nodes}
    triple_map = {str(r["day"]): r["cnt"] for r in daily_triples}
    all_days = sorted(set(node_map) | set(triple_map))
    daily = [
        {
            "date": day,
            "nodes_created": node_map.get(day, 0),
            "triples_created": triple_map.get(day, 0),
        }
        for day in all_days
    ]
    return {
        "nodes_total": nodes_total,
        "triples_total": triples_total,
        "daily": daily,
    }


# ---------------------------------------------------------------------------
# GET /stats/agents
# ---------------------------------------------------------------------------

@router.get("/agents")
async def stats_agents(
    workspace_id: Optional[int] = Query(None),
    period: str = Query("7d"),
    actor: dict = Depends(get_current_user),
) -> dict:
    """Actividad por agente en el período."""
    days = _period_to_days(period)
    is_super = bool(actor.get("is_super"))
    pool = await get_pool()

    async with pool.acquire() as conn:
        if not is_super:
            visible = await visible_project_ids(conn, actor)
            if not visible:
                return {"period": period, "agents": []}
            project_filter = "AND m.project_id = ANY($2::int[])"
            having_clause = "HAVING COUNT(m.id) > 0"
            params: list = [days, list(visible)]
        else:
            project_filter = ""
            having_clause = ""
            params = [days]

        ws_clause = ""
        if workspace_id is not None:
            params.append(workspace_id)
            ws_clause = f"AND m.workspace_id = ${len(params)}"

        rows = await conn.fetch(f"""
            SELECT a.identifier,
                   COUNT(m.id) AS memories_created,
                   MAX(a.last_seen) AS last_activity
            FROM agents a
            LEFT JOIN memories m ON m.agent_id = a.id
                AND m.created_at >= NOW() - make_interval(days => $1)
                {project_filter}
                {ws_clause}
            GROUP BY a.id, a.identifier, a.last_seen
            {having_clause}
            ORDER BY memories_created DESC
        """, *params)

        # searches from search_log — filter by visible project_ids
        if not is_super:
            search_rows = await conn.fetch(f"""
                SELECT a.identifier, COUNT(sl.id) AS searches
                FROM agents a
                LEFT JOIN search_log sl ON sl.agent_id = a.id
                    AND sl.created_at >= NOW() - make_interval(days => $1)
                    AND sl.project_ids && $2::int[]
                GROUP BY a.identifier
            """, days, list(visible))
        else:
            search_rows = await conn.fetch(f"""
                SELECT a.identifier, COUNT(sl.id) AS searches
                FROM agents a
                LEFT JOIN search_log sl ON sl.agent_id = a.id
                    AND sl.created_at >= NOW() - make_interval(days => $1)
                GROUP BY a.identifier
            """, days)

    search_map = {r["identifier"]: r["searches"] for r in search_rows}
    agents = [
        {
            "identifier": r["identifier"],
            "memories_created": r["memories_created"],
            "searches": search_map.get(r["identifier"], 0),
            "last_activity": r["last_activity"].isoformat() if r["last_activity"] else None,
        }
        for r in rows
    ]
    return {"period": period, "agents": agents}


# ---------------------------------------------------------------------------
# GET /stats/search
# ---------------------------------------------------------------------------

@router.get("/search")
async def stats_search(
    period: str = Query("7d"),
    actor: dict = Depends(get_current_user),
) -> dict:
    """Métricas de búsqueda desde search_log."""
    days = _period_to_days(period)
    is_super = bool(actor.get("is_super"))
    pool = await get_pool()

    async with pool.acquire() as conn:
        if not is_super:
            visible = await visible_project_ids(conn, actor)
            if not visible:
                return {"available": True, "period": period, "total_queries": 0,
                        "failed_count": 0, "avg_latency_ms": None, "p95_latency_ms": None}
            rows = await conn.fetch("""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE failed) AS failed_count,
                       AVG(latency_ms) AS avg_latency_ms,
                       PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_latency_ms
                FROM search_log
                WHERE created_at >= NOW() - make_interval(days => $1)
                  AND project_ids && $2::int[]
            """, days, list(visible))
        else:
            rows = await conn.fetch("""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE failed) AS failed_count,
                       AVG(latency_ms) AS avg_latency_ms,
                       PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_latency_ms
                FROM search_log
                WHERE created_at >= NOW() - make_interval(days => $1)
            """, days)

    r = rows[0]
    return {
        "available": True,
        "period": period,
        "total_queries": r["total"],
        "failed_count": r["failed_count"],
        "avg_latency_ms": round(float(r["avg_latency_ms"]), 1) if r["avg_latency_ms"] else None,
        "p95_latency_ms": round(float(r["p95_latency_ms"]), 1) if r["p95_latency_ms"] else None,
    }


# ---------------------------------------------------------------------------
# GET /stats/system
# ---------------------------------------------------------------------------

@router.get("/system")
async def stats_system(actor: dict = Depends(get_current_user)) -> dict:
    """Métricas de sistema: embeddings VRAM, DB counts, media."""
    if not bool(actor.get("is_super")):
        raise HTTPException(403, "stats/system requires super access")
    pool = await get_pool()

    # DB counts
    async with pool.acquire() as conn:
        memories_count = await conn.fetchval("SELECT COUNT(*) FROM memories")
        nodes_count = await conn.fetchval("SELECT COUNT(*) FROM nodes")
        triples_count = await conn.fetchval("SELECT COUNT(*) FROM triples")
        # Media: count non-null media_path entries in memories
        media_count = await conn.fetchval(
            "SELECT COUNT(*) FROM memories WHERE media_path IS NOT NULL"
        )

    # Embeddings health
    embeddings_info: dict = {"status": "unknown"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_EMBEDDINGS_URL}/health/detailed")
            if resp.status_code == 200:
                body = resp.json()
                embeddings_info = {
                    "status": "ok",
                    "vram_used_gb": body.get("vram_used_gb"),
                    "vram_total_gb": body.get("vram_total_gb"),
                    **{k: v for k, v in body.items() if k in _EMBEDDINGS_ALLOWED_FIELDS},
                }
            else:
                embeddings_info = {"status": "error", "http_status": resp.status_code}
    except Exception:
        embeddings_info = {"status": "unreachable", "error": "embeddings service unreachable"}

    return {
        "embeddings": embeddings_info,
        "db": {
            "memories_count": memories_count,
            "nodes_count": nodes_count,
            "triples_count": triples_count,
        },
        "media": {
            "files_count": media_count,
            "note": "count of memories with media_path (filesystem scan not available in container)",
        },
    }


# ---------------------------------------------------------------------------
# GET /stats/timeline
# ---------------------------------------------------------------------------

@router.get("/timeline")
async def stats_timeline(
    period: int = Query(30, ge=1, le=365, description="Days of history"),
    actor: dict = Depends(get_current_user),
) -> dict:
    is_super = bool(actor.get("is_super"))
    pool = await get_pool()

    async with pool.acquire() as conn:
        if is_super:
            mem_filter = ""
            doc_filter = ""
            search_filter = ""
            params: list = [period]
        else:
            visible = await visible_project_ids(conn, actor)
            if not visible:
                return {"period_days": period, "timeline": []}
            visible_list = list(visible)
            mem_filter = "AND project_id = ANY($2::int[])"
            doc_filter = "AND project_id = ANY($2::int[])"
            search_filter = "AND project_ids && $2::int[]"
            params = [period, visible_list]

        rows = await conn.fetch(f"""
            WITH gs AS (
                SELECT gs::date AS day
                FROM generate_series(
                    (now() - (interval '1 day' * $1))::date,
                    now()::date,
                    '1 day'::interval
                ) gs
            ),
            mem AS (
                SELECT DATE(created_at) AS day, COUNT(*) AS cnt
                FROM memories
                WHERE created_at >= now() - interval '1 day' * $1
                AND staleness != 'archived'
                {mem_filter}
                GROUP BY DATE(created_at)
            ),
            docs AS (
                SELECT DATE(created_at) AS day, COUNT(*) AS cnt
                FROM documents
                WHERE created_at >= now() - interval '1 day' * $1
                AND status != 'deleted'
                {doc_filter}
                GROUP BY DATE(created_at)
            ),
            searches AS (
                SELECT DATE(created_at) AS day, COUNT(*) AS cnt
                FROM search_log
                WHERE created_at >= now() - interval '1 day' * $1
                {search_filter}
                GROUP BY DATE(created_at)
            )
            SELECT
                gs.day,
                COALESCE(mem.cnt, 0) AS memories,
                COALESCE(docs.cnt, 0) AS documents,
                COALESCE(searches.cnt, 0) AS searches
            FROM gs
            LEFT JOIN mem ON mem.day = gs.day
            LEFT JOIN docs ON docs.day = gs.day
            LEFT JOIN searches ON searches.day = gs.day
            ORDER BY gs.day
        """, *params)

    timeline = [
        {
            "date": str(r["day"]),
            "memories": r["memories"],
            "documents": r["documents"],
            "searches": r["searches"],
        }
        for r in rows
    ]
    return {"period_days": period, "timeline": timeline}


# ---------------------------------------------------------------------------
# Task 5.17 — Observabilidad cognitiva
# ---------------------------------------------------------------------------

@router.get("/knowledge")
async def knowledge_stats(
    project_id: Optional[int] = Query(None, description="Scope memory counts to a project. Graph/entity metrics remain system-wide."),
    actor: dict = Depends(get_current_user),
) -> dict:
    """Knowledge graph health metrics. Super-only."""
    if not actor.get("is_super"):
        raise HTTPException(403, "Super-only endpoint")
    pool = await get_pool()
    async with pool.acquire() as conn:
        data: dict = {}
        data["entity_count"] = await conn.fetchval(
            "SELECT count(*) FROM nodes WHERE status = 'active'"
        )
        data["merged_entity_count"] = await conn.fetchval(
            "SELECT count(*) FROM nodes WHERE status = 'merged'"
        )
        data["alias_candidate_count"] = await conn.fetchval(
            "SELECT count(*) FROM entity_alias_candidates WHERE status = 'pending'"
        )
        data["merge_count"] = await conn.fetchval(
            "SELECT count(*) FROM entity_merge_log WHERE undone_at IS NULL"
        )
        data["orphan_entity_count"] = await conn.fetchval(
            """SELECT count(*) FROM nodes n
               WHERE status = 'active'
                 AND NOT EXISTS (SELECT 1 FROM memory_entity_links mel WHERE mel.entity_node_id = n.id)
                 AND NOT EXISTS (SELECT 1 FROM document_entity_links del WHERE del.entity_node_id = n.id)"""
        )
        if project_id is None:
            data["stale_memory_count"] = await conn.fetchval(
                "SELECT count(*) FROM memories WHERE staleness = 'stale'"
            )
            data["dormant_memory_count"] = await conn.fetchval(
                "SELECT count(*) FROM memories WHERE staleness = 'dormant'"
            )
            data["duplicate_candidate_count"] = await conn.fetchval(
                "SELECT count(*) FROM related_documents WHERE confirmed_by IS NULL"
            )
        else:
            data["stale_memory_count"] = await conn.fetchval(
                "SELECT count(*) FROM memories WHERE staleness = 'stale' AND project_id = $1",
                project_id,
            )
            data["dormant_memory_count"] = await conn.fetchval(
                "SELECT count(*) FROM memories WHERE staleness = 'dormant' AND project_id = $1",
                project_id,
            )
            data["duplicate_candidate_count"] = await conn.fetchval(
                "SELECT count(*) FROM related_documents WHERE confirmed_by IS NULL"
            )
        data["graph_density"] = await conn.fetchval(
            """SELECT CASE
                 WHEN (SELECT count(*) FROM nodes WHERE status = 'active') < 2 THEN 0.0
                 ELSE (SELECT count(*)::float FROM triples t
                       JOIN nodes n1 ON n1.id = t.subject_id AND n1.status = 'active'
                       JOIN nodes n2 ON n2.id = t.object_id AND n2.status = 'active')
                      / ((SELECT count(*) FROM nodes WHERE status = 'active')
                         * ((SELECT count(*) FROM nodes WHERE status = 'active') - 1))
               END"""
        )
        top_rows = await conn.fetch(
            """SELECT n.id, n.name, n.type, count(*) AS degree
               FROM nodes n
               LEFT JOIN triples t ON t.subject_id = n.id OR t.object_id = n.id
               WHERE n.status = 'active'
               GROUP BY n.id, n.name, n.type
               ORDER BY degree DESC
               LIMIT 10"""
        )
        data["top_entities_by_degree"] = [dict(r) for r in top_rows]
    return data


# ---------------------------------------------------------------------------
# Metacognition stats models
# ---------------------------------------------------------------------------

class ClusteringMetrics(BaseModel):
    silhouette_cosine: Optional[float] = None
    silhouette_combined: Optional[float] = None
    avg_cluster_size: Optional[float] = None
    graph_led_pct: Optional[float] = None
    graph_led_useful_pct: Optional[float] = None


class ForesightMetrics(BaseModel):
    active_count: int = 0
    expired_unused_count: int = 0
    auto_extracted_count: int = 0
    precision_estimate: Optional[float] = None


class SkillsMetrics(BaseModel):
    total: int = 0
    active: int = 0
    stale: int = 0
    avg_success_rate: Optional[float] = None


class BriefingMetrics(BaseModel):
    avg_items: Optional[float] = None
    nuisance_rate: Optional[float] = None
    dismiss_rate: Optional[float] = None


class IdentityMetrics(BaseModel):
    open_tensions: int = 0
    resolved_30d: int = 0
    dismissed_30d: int = 0


class CellsMetrics(BaseModel):
    total_runs_30d: int = 0
    total_cost_30d: Optional[float] = None
    error_rate: Optional[float] = None
    runs_by_type: dict[str, int] = Field(default_factory=dict)


class MetacognitionStatsResponse(BaseModel):
    clustering: ClusteringMetrics
    foresight: ForesightMetrics
    skills: SkillsMetrics
    briefing: BriefingMetrics
    identity: IdentityMetrics
    cells: CellsMetrics
    last_computed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# GET /stats/metacognition
# ---------------------------------------------------------------------------

@router.get("/metacognition")
async def stats_metacognition(actor: dict = Depends(get_current_user)) -> MetacognitionStatsResponse:
    if not actor.get("is_super"):
        raise HTTPException(403, "stats/metacognition requires super access")
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Clustering — from last consolidation run
        last_run = await conn.fetchrow("""
            SELECT metrics, finished_at FROM cell_runs
            WHERE cell_type='consolidation' AND status='completed'
            ORDER BY finished_at DESC LIMIT 1
        """)
        import json as _json
        _raw_metrics = last_run["metrics"] if last_run else {}
        if isinstance(_raw_metrics, str):
            _raw_metrics = _json.loads(_raw_metrics)
        cm = (_raw_metrics or {}).get("clustering", {})
        avg_size = None  # clusters table dropped in KnowTwin (metacognition stripped)

        # Foresight
        active_f = await conn.fetchval("""
            SELECT COUNT(*) FROM memories WHERE foresight_start IS NOT NULL AND foresight_end > NOW()
              AND (metadata->>'foresight_dismissed' IS NULL OR metadata->>'foresight_dismissed' != 'true')
        """)
        expired_unused = await conn.fetchval("""
            SELECT COUNT(*) FROM memories WHERE foresight_start IS NOT NULL AND foresight_end <= NOW()
              AND access_count = 0
        """)
        auto_extracted = await conn.fetchval("""
            SELECT COUNT(*) FROM memories WHERE foresight_start IS NOT NULL
              AND metadata->>'foresight_source' = 'cell'
        """)

        # Skills
        total_sk = await conn.fetchval("SELECT COUNT(*) FROM memories WHERE type='skill'")
        active_sk = await conn.fetchval(
            "SELECT COUNT(*) FROM memories WHERE type='skill' AND metadata @> '{\"status\":\"active\"}'::jsonb")
        stale_sk = await conn.fetchval(
            "SELECT COUNT(*) FROM memories WHERE type='skill' AND metadata @> '{\"status\":\"stale\"}'::jsonb")

        # Identity
        open_t = await conn.fetchval("""
            SELECT COUNT(*) FROM memories WHERE 'identity_tension' = ANY(tags)
              AND (metadata->>'tension_status' IS NULL OR metadata->>'tension_status' = 'open')
        """)
        resolved_30d = await conn.fetchval("""
            SELECT COUNT(*) FROM memories WHERE 'identity_tension' = ANY(tags)
              AND metadata->>'tension_status' = 'resolve' AND updated_at > NOW()-INTERVAL '30 days'
        """)
        dismissed_30d = await conn.fetchval("""
            SELECT COUNT(*) FROM memories WHERE 'identity_tension' = ANY(tags)
              AND metadata->>'tension_status' = 'dismiss' AND updated_at > NOW()-INTERVAL '30 days'
        """)

        # Cells
        runs_30d = await conn.fetchval(
            "SELECT COUNT(*) FROM cell_runs WHERE started_at > NOW()-INTERVAL '30 days'")
        cost_30d = await conn.fetchval(
            "SELECT SUM(cost_usd) FROM cell_runs WHERE started_at > NOW()-INTERVAL '30 days'")
        errors_30d = await conn.fetchval(
            "SELECT COUNT(*) FROM cell_runs WHERE status='failed' AND started_at > NOW()-INTERVAL '30 days'")
        runs_by = await conn.fetch(
            "SELECT cell_type, COUNT(*) AS cnt FROM cell_runs WHERE started_at > NOW()-INTERVAL '30 days' GROUP BY cell_type")

    return {
        "clustering": {
            "silhouette_cosine": cm.get("silhouette_cosine"),
            "silhouette_combined": cm.get("silhouette_combined"),
            "avg_cluster_size": float(avg_size) if avg_size else None,
            "graph_led_pct": cm.get("graph_led_pct"),
            "graph_led_useful_pct": cm.get("graph_led_useful_pct"),
        },
        "foresight": {
            "active_count": active_f, "expired_unused_count": expired_unused,
            "auto_extracted_count": auto_extracted, "precision_estimate": None,
        },
        "skills": {"total": total_sk, "active": active_sk, "stale": stale_sk},
        "briefing": {"avg_items": None, "nuisance_rate": None, "dismiss_rate": None},
        "identity": {"open_tensions": open_t, "resolved_30d": resolved_30d, "dismissed_30d": dismissed_30d},
        "cells": {
            "total_runs_30d": runs_30d,
            "total_cost_30d": float(cost_30d) if cost_30d else None,
            "error_rate": round(errors_30d / max(runs_30d, 1), 3) if runs_30d else None,
            "runs_by_type": {r["cell_type"]: r["cnt"] for r in runs_by},
        },
        "last_computed_at": last_run["finished_at"] if last_run else None,
    }
