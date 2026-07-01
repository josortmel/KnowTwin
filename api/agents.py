"""Agent management endpoints (KnowTwin).

EcoDB's agent_identity fragment versioning and observed-identity / identity-tension
(metacognition) surface are STRIPPED in the KnowTwin fork (P1.1) — KnowTwin has no
agent-identity concept. What remains is plain agent CRUD/management:

- PATCH /agents/{agent_identifier}      → update cognition_class/display_name/description
- GET   /api/v1/agents                  → list agents (super sees all, else own)
- POST  /api/v1/agents                  → create agent (super only)

404 semantics for _resolve_agent_or_404 preserved (anti discovery-oracle of
identifiers): "not found" and "found but not owner" both return 404.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from auth import get_current_user
from db import get_pool


MAX_AGENT_IDENTIFIER_LEN = 200  # `agents.identifier` es TEXT, sin límite duro en schema.


router = APIRouter(prefix="/agents", tags=["agents"])

# v1.3 management endpoints — mounted under /api/v1 in main.py (the legacy
# `router` above is mounted at /agents).
router_v1 = APIRouter(prefix="/agents", tags=["agents"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class AgentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cognition_class: Optional[str] = Field(None, pattern="^(narrative|work|mixed)$")
    display_name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)


class AgentSummary(BaseModel):
    id: int
    identifier: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    active: bool
    cognition_class: str
    last_seen: Optional[datetime] = None
    cell_configs_count: int
    last_cell_run: Optional[datetime] = None


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identifier: str = Field(..., min_length=1, max_length=MAX_AGENT_IDENTIFIER_LEN)
    display_name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    cognition_class: str = Field("work", pattern="^(narrative|work|mixed)$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve_agent_or_404(conn, actor: dict, agent_identifier: str) -> dict:
    """Resuelve agent_identifier → row de agents + verifica permisos.

    404 igual para "no existe" y "existe sin permiso" — evita discovery oracle
    de identifiers válidos. super bypasea.
    """
    row = await conn.fetchrow(
        "SELECT id, identifier, user_id FROM agents WHERE identifier = $1 AND active = true",
        agent_identifier,
    )
    if row is None:
        raise HTTPException(404, f"agent {agent_identifier!r} not found")
    if actor.get("is_super"):
        return dict(row)
    if row["user_id"] is not None and int(row["user_id"]) == int(actor["sub"]):
        return dict(row)
    raise HTTPException(404, f"agent {agent_identifier!r} not found")


# ---------------------------------------------------------------------------
# PATCH /agents/{agent_identifier}
# ---------------------------------------------------------------------------

@router.patch("/{agent_identifier}")
async def patch_agent(
    agent_identifier: str,
    body: AgentPatch,
    actor: dict = Depends(get_current_user),
) -> dict:
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    pool = await get_pool()
    async with pool.acquire() as conn:
        agent = await _resolve_agent_or_404(conn, actor, agent_identifier)
        set_parts: list = []
        params: list = []
        for key, value in fields.items():
            params.append(value)
            set_parts.append(f"{key} = ${len(params)}")
        params.append(agent["id"])
        await conn.execute(
            f"UPDATE agents SET {', '.join(set_parts)} WHERE id = ${len(params)}",
            *params)
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'patch_agent', 'agent', $2::text, $3::jsonb, $4)""",
            int(actor["sub"]), str(agent["id"]),
            json.dumps(fields),
            actor.get("organization_id"))
    return {"ok": True, "agent_identifier": agent_identifier}


# ---------------------------------------------------------------------------
# v1.3 management endpoints — GET/POST /api/v1/agents (router_v1)
# ---------------------------------------------------------------------------

_AGENT_SUMMARY_SELECT = """
    SELECT a.id, a.identifier, a.display_name, a.description, a.active,
           a.cognition_class, a.last_seen,
           (SELECT COUNT(*) FROM cell_task_configs c WHERE c.agent_id = a.id)
               AS cell_configs_count,
           (SELECT MAX(finished_at) FROM cell_runs cr WHERE cr.agent_id = a.id)
               AS last_cell_run
    FROM agents a
"""


@router_v1.get("")
async def list_agents(actor: dict = Depends(get_current_user)) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if actor.get("is_super"):
            rows = await conn.fetch(
                _AGENT_SUMMARY_SELECT + " ORDER BY a.identifier")
        else:
            rows = await conn.fetch(
                _AGENT_SUMMARY_SELECT + " WHERE a.user_id = $1 ORDER BY a.identifier",
                int(actor["sub"]))
    items = [AgentSummary(**dict(r)) for r in rows]
    return {"items": items, "total": len(items)}


@router_v1.post("", status_code=201)
async def create_agent(
    body: AgentCreate,
    actor: dict = Depends(get_current_user),
) -> AgentSummary:
    if not actor.get("is_super"):
        raise HTTPException(403, "agent creation requires super access")
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            new_id = await conn.fetchval(
                """
                INSERT INTO agents
                    (identifier, display_name, description, cognition_class, user_id)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                body.identifier, body.display_name, body.description,
                body.cognition_class, int(actor["sub"]))
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, f"agent {body.identifier!r} already exists")
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'create_agent', 'agent', $2::text, $3::jsonb, $4)""",
            int(actor["sub"]), str(new_id),
            json.dumps({"identifier": body.identifier,
                        "cognition_class": body.cognition_class}),
            actor.get("organization_id"))
        row = await conn.fetchrow(
            _AGENT_SUMMARY_SELECT + " WHERE a.id = $1", new_id)
    return AgentSummary(**dict(row))
