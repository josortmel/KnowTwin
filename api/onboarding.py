"""Endpoint de onboarding por proyecto — ."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_user
from db import get_pool
from permissions import visible_project_ids

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("/{project_id}")
async def get_onboarding(
    project_id: int,
    format: Literal["agent", "dashboard"] = Query("agent"),
    actor: dict = Depends(get_current_user),
) -> dict | str:
    """Resumen de onboarding de un proyecto para agente o dashboard."""
    is_super = bool(actor.get("is_super"))
    pool = await get_pool()

    async with pool.acquire() as conn:
        # Verificar acceso al proyecto
        if not is_super:
            visible = await visible_project_ids(conn, actor)
            if project_id not in visible:
                raise HTTPException(403, "no access to specified project")

        # Info del proyecto
        project = await conn.fetchrow(
            "SELECT id, name FROM projects WHERE id = $1", project_id
        )
        if project is None:
            raise HTTPException(404, f"project {project_id} not found")

        # Últimas 5 decisiones
        decisions = await conn.fetch("""
            SELECT id, content, created_at
            FROM memories
            WHERE project_id = $1 AND type = 'decision' AND visibility = 'public'
            ORDER BY created_at DESC
            LIMIT 5
        """, project_id)

        # Agentes activos (last_seen en últimos 5 minutos)
        active_agents = await conn.fetch("""
            SELECT DISTINCT a.identifier, a.last_seen
            FROM agents a
            JOIN memories m ON m.agent_id = a.id
            WHERE m.project_id = $1
              AND a.last_seen >= NOW() - INTERVAL '5 minutes'
            ORDER BY a.last_seen DESC
        """, project_id)

        # Memorias obsoletas (weight < 0.3)
        stale_count = await conn.fetchval("""
            SELECT COUNT(*) FROM memories
            WHERE project_id = $1 AND weight < 0.3 AND visibility = 'public'
        """, project_id)

        # Última actividad
        last_activity = await conn.fetchval("""
            SELECT MAX(created_at) FROM memories
            WHERE project_id = $1 AND visibility = 'public'
        """, project_id)

    if format == "agent":
        decision_texts = [d["content"][:120] for d in decisions]
        agent_ids = [a["identifier"] for a in active_agents]
        last_ts = last_activity.isoformat() if last_activity else "ninguna"
        text = (
            f"Proyecto: {project['name']}. "
            f"Últimas 5 decisiones: {decision_texts or ['ninguna']}. "
            f"Agentes activos: {agent_ids or ['ninguno']}. "
            f"Última actividad: {last_ts}."
        )
        return {"format": "agent", "text": text}

    # dashboard format
    return {
        "format": "dashboard",
        "project_name": project["name"],
        "health": {
            "status": "ok",
            "stale_count": stale_count,
        },
        "recent_decisions": [
            {
                "id": str(d["id"]),
                "content": d["content"][:200],
                "created_at": d["created_at"].isoformat(),
            }
            for d in decisions
        ],
        "active_agents": [
            {
                "identifier": a["identifier"],
                "last_seen": a["last_seen"].isoformat() if a["last_seen"] else None,
            }
            for a in active_agents
        ],
        "contradictions": None,  # stub — not implemented yet
        "last_activity": last_activity.isoformat() if last_activity else None,
    }
