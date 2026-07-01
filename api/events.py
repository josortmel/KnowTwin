"""Endpoints de eventos de agentes — .9 SSE.

SSE endpoint for the frontend dashboard.
Archivo: events.py | Endpoint: GET /api/v1/events/stream
Hooks activos: memory_created, search_completed, contradiction_detected, tension_detected, duplicate_detected, document_indexed
The frontend connects with EventSource("/api/v1/events/stream")
"""
from __future__ import annotations

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from auth import get_current_user
from db import get_pool

_INTERNAL_BROADCAST_SECRET = __import__("os").environ.get("INTERNAL_BROADCAST_SECRET", "")

router = APIRouter(prefix="/events", tags=["events"])

# Cola global de eventos (in-memory, single-tenant)
_event_queues: list[asyncio.Queue] = []


async def resolve_org_id_from_project(conn, project_id: int) -> int | None:
    """Resolve organization_id from project via workspace. conn must be asyncpg.Connection, NOT Pool."""
    row = await conn.fetchrow(
        "SELECT w.organization_id FROM projects p JOIN workspaces w ON p.workspace_id = w.id WHERE p.id = $1",
        project_id,
    )
    return row["organization_id"] if row else None


async def broadcast_event(event_type: str, data: dict, org_id: int | None = None) -> None:
    """Broadcast SSE event. org_id=None → super-only. org_id=N → same org + super."""
    event_type = event_type.replace("\n", "").replace("\r", "")
    payload = json.dumps(data)
    for q in _event_queues:
        try:
            q.put_nowait({"event": event_type, "data": payload, "org_id": org_id})
        except asyncio.QueueFull:
            pass


class SessionEventBody(BaseModel):
    agent_identifier: str = Field(..., min_length=1, max_length=128)
    event: Literal["connected", "disconnected"]


@router.post("/session")
async def post_session_event(
    body: SessionEventBody,
    actor: dict = Depends(get_current_user),
) -> dict:
    """Registra conexión/desconexión de agente y actualiza last_seen."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        agent_row = await conn.fetchrow(
            "SELECT id, user_id FROM agents WHERE identifier = $1",
            body.agent_identifier,
        )
        if agent_row is None:
            raise HTTPException(404, f"agent '{body.agent_identifier}' not found")
        try:
            actor_id = int(actor["sub"])
        except (ValueError, TypeError):
            raise HTTPException(401, "invalid token subject")
        is_super = bool(actor.get("is_super"))
        if agent_row["user_id"] != actor_id and not is_super:
            raise HTTPException(403, "cannot update session for agent owned by another user")
        row = await conn.fetchrow(
            """
            UPDATE agents
            SET last_seen = NOW()
            WHERE id = $1
            RETURNING identifier, last_seen
            """,
            agent_row["id"],
        )
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'agent_session', 'agent', $2, $3::jsonb, $4)""",
            int(actor["sub"]), body.agent_identifier,
            json.dumps({"event": body.event}),
            actor.get("organization_id"),
        )
    await broadcast_event(f"agent_{body.event}", {"agent_identifier": body.agent_identifier}, org_id=actor.get("organization_id"))
    return {
        "ok": True,
        "agent_identifier": row["identifier"],
        "event": body.event,
        "last_seen": row["last_seen"].isoformat(),
    }


@router.get("/stream")
async def event_stream(
    request: Request,
    actor: dict = Depends(get_current_user),
):
    """SSE stream — emits real-time events to the dashboard. Org-filtered."""
    client_org_id: int | None = actor.get("organization_id")
    client_is_super: bool = actor.get("is_super", False)

    async def generate():
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        _event_queues.append(queue)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    event_org_id = event.get("org_id")
                    if event_org_id is not None:
                        if not client_is_super and client_org_id != event_org_id:
                            continue
                    elif not client_is_super:
                        continue
                    yield f"event: {event['event']}\ndata: {event['data']}\n\n"
                except asyncio.TimeoutError:
                    yield "event: keepalive\ndata: \n\n"
        finally:
            _event_queues.remove(queue)

    return StreamingResponse(generate(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Task 4.13 — Internal broadcast endpoint (worker → SSE clients)
# ---------------------------------------------------------------------------

class BroadcastBody(BaseModel):
    event_type: str = Field(..., min_length=1, max_length=128)
    data: dict = Field(default_factory=dict)
    org_id: int | None = None


@router.post("/broadcast", status_code=204, include_in_schema=False)
async def broadcast_internal(
    body: BroadcastBody,
    request: Request,
) -> None:
    """Internal-only SSE broadcast. Called by worker process (same Docker network).

    Accepts: Bearer JWT (super) OR X-Internal-Secret header.
    No external exposure — only reachable via ECODB_API_INTERNAL_URL.
    """
    auth_header = request.headers.get("Authorization", "")
    secret_header = request.headers.get("X-Internal-Secret", "")

    authorized = False
    import hmac as _hmac
    if _INTERNAL_BROADCAST_SECRET and _hmac.compare_digest(secret_header, _INTERNAL_BROADCAST_SECRET):
        authorized = True
    elif auth_header.startswith("Bearer "):
        try:
            from auth import decode_jwt
            payload = decode_jwt(auth_header[7:])
            if payload.get("is_super"):
                authorized = True
        except Exception:
            pass

    if not authorized:
        raise HTTPException(403, "internal broadcast requires X-Internal-Secret or Bearer token")

    await broadcast_event(body.event_type, body.data, org_id=body.org_id)
