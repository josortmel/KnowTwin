"""KnowTwin Interview API — session CRUD + /respond + /voice + WebSocket."""
from __future__ import annotations

import json
import logging
import os
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from auth import get_current_user
from auth import resolve_user_from_api_key as _resolve_key
from db import get_pool
from permissions import check_access

log = logging.getLogger("knowtwin.interviews")

router = APIRouter(prefix="/interviews", tags=["interviews"])


def _check_session_ownership(actor: dict, row, role: str | None = None) -> None:
    """Employee must own session. Curator+ bypasses (oversight access)."""
    if role and role in ("curator", "admin"):
        return
    if int(actor["sub"]) != row["employee_id"]:
        raise HTTPException(403, "not your session")

_ws_connections: dict[str, list[WebSocket]] = {}


class SessionCreate(BaseModel):
    project_id: int = Field(..., gt=0)
    topic: str = Field(..., min_length=1, max_length=500)
    planned_duration_min: int = Field(45, ge=5, le=240)


class RespondRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
async def create_session(
    body: SessionCreate,
    actor: dict = Depends(get_current_user),
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        role = await check_access(conn, actor, body.project_id, "employee")

        row = await conn.fetchrow(
            """
            INSERT INTO interview_sessions (project_id, employee_id, topic, planned_duration_min, status)
            VALUES ($1, $2, $3, $4, 'scheduled')
            RETURNING id, project_id, employee_id, topic, status, planned_duration_min, created_at
            """,
            body.project_id, int(actor["sub"]), body.topic, body.planned_duration_min,
        )
        return _session_dict(row)


@router.get("")
async def list_sessions(
    project_id: int = Query(..., gt=0),
    actor: dict = Depends(get_current_user),
) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await check_access(conn, actor, project_id, "employee")
        rows = await conn.fetch(
            "SELECT id, project_id, employee_id, topic, status, claims_extracted, "
            "created_at, completed_at FROM interview_sessions "
            "WHERE project_id = $1 ORDER BY created_at DESC",
            project_id,
        )
        return [_session_dict(r) for r in rows]


@router.get("/{session_id}")
async def get_session(
    session_id: UUID,
    actor: dict = Depends(get_current_user),
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM interview_sessions WHERE id = $1", session_id
        )
        if row is None:
            raise HTTPException(404, "session not found")
        role = await check_access(conn, actor, row["project_id"], "employee")
        _check_session_ownership(actor, row, role)
        return _session_dict(row)


@router.post("/{session_id}/start")
async def start_session(
    session_id: UUID,
    actor: dict = Depends(get_current_user),
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM interview_sessions WHERE id = $1", session_id
        )
        if row is None:
            raise HTTPException(404, "session not found")
        role = await check_access(conn, actor, row["project_id"], "employee")
        _check_session_ownership(actor, row, role)
        if row["status"] != "scheduled":
            raise HTTPException(409, f"session is {row['status']}, not scheduled")

        from interviewer import InterviewState, prepare_dossier, save_state

        state = InterviewState(str(session_id), row["project_id"], row["employee_id"])
        state = await prepare_dossier(conn, state)

        from interviewer import open_topic
        state = await open_topic(conn, state)
        await save_state(conn, state)

        await conn.execute(
            "UPDATE interview_sessions SET status = 'in_progress' WHERE id = $1",
            session_id,
        )
        return {"status": "in_progress", "topic": state.current_topic,
                "session_id": str(session_id)}


@router.post("/{session_id}/respond")
async def respond(
    session_id: UUID,
    body: RespondRequest,
    actor: dict = Depends(get_current_user),
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM interview_sessions WHERE id = $1", session_id
        )
        if row is None:
            raise HTTPException(404, "session not found")
        role = await check_access(conn, actor, row["project_id"], "employee")
        _check_session_ownership(actor, row, role)
        if row["status"] != "in_progress":
            raise HTTPException(409, f"session is {row['status']}, not in_progress")

        from interviewer import load_state, conduct_turn, close_topic, open_topic, write_rollup

        state = await load_state(conn, str(session_id))
        if state is None:
            raise HTTPException(500, "session state not found")

        if state.state == "close_topic":
            state = await close_topic(conn, state)
            if state.state == "open_topic":
                state = await open_topic(conn, state)

        if state.state == "write_rollup":
            rollup = await write_rollup(conn, state)
            await _ws_broadcast(str(session_id), "topic_change", {"rollup": True})
            return {"status": "completed", "rollup": rollup}

        result = await conduct_turn(conn, state, body.text)

        for cid in result.get("claims_created", []):
            await _ws_broadcast(str(session_id), "new_claim", {"claim_id": cid})

        if result.get("converged"):
            await _ws_broadcast(str(session_id), "topic_change",
                                {"topic": state.current_topic, "converged": True})

        coverage = None
        try:
            cov_row = await conn.fetchrow(
                "SELECT overall_coverage_pct FROM (SELECT ROUND((SUM(covered_criticality) / "
                "NULLIF(SUM(expected_count * expected_criticality), 0) * 100)::numeric, 1) AS overall_coverage_pct "
                "FROM entity_coverage WHERE project_id = $1) t",
                row["project_id"],
            )
            if cov_row:
                coverage = float(cov_row["overall_coverage_pct"] or 0)
                await _ws_broadcast(str(session_id), "coverage_update",
                                    {"coverage_pct": coverage})
        except Exception:
            pass

        return {
            "turn": result["turn"],
            "claims_created": result["claims_created"],
            "turn_value": result["turn_value"],
            "converged": result["converged"],
            "topic": result.get("topic"),
            "state": result["state"],
            "coverage_pct": coverage,
        }


_MEDIA_STORE = os.environ.get("MEDIA_STORE_DIR", "/app/media")


@router.post("/{session_id}/voice")
async def voice(
    session_id: UUID,
    file: UploadFile = File(...),
    actor: dict = Depends(get_current_user),
) -> dict:
    """Voice note → STT → same /respond path."""
    import uuid as _uuid
    from parsers import AUDIO_EXTENSIONS, transcribe_audio

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM interview_sessions WHERE id = $1", session_id
        )
        if row is None:
            raise HTTPException(404, "session not found")
        role = await check_access(conn, actor, row["project_id"], "employee")
        _check_session_ownership(actor, row, role)
        if row["status"] != "in_progress":
            raise HTTPException(409, f"session is {row['status']}, not in_progress")

    if not file.filename:
        raise HTTPException(400, "file has no name")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in AUDIO_EXTENSIONS:
        raise HTTPException(422, f"unsupported audio format: {ext}")

    os.makedirs(_MEDIA_STORE, exist_ok=True)
    stored = os.path.join(_MEDIA_STORE, f"{_uuid.uuid4()}{ext}")
    content = await file.read()
    with open(stored, "wb") as f:
        f.write(content)

    try:
        result = await transcribe_audio(stored)
        text = result.get("text", "") if isinstance(result, dict) else str(result)
        if hasattr(result, "text"):
            text = result.text
    except ValueError as exc:
        os.unlink(stored)
        raise HTTPException(422, str(exc))
    except Exception as exc:
        os.unlink(stored)
        raise HTTPException(500, f"transcription failed: {type(exc).__name__}")
    finally:
        if os.path.exists(stored):
            os.unlink(stored)

    if not text or not text.strip():
        raise HTTPException(422, "transcription produced no text")

    body = RespondRequest(text=text.strip()[:5000])
    return await respond(session_id, body, actor)


@router.post("/{session_id}/close")
async def close_session(
    session_id: UUID,
    actor: dict = Depends(get_current_user),
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM interview_sessions WHERE id = $1", session_id
        )
        if row is None:
            raise HTTPException(404, "session not found")
        role = await check_access(conn, actor, row["project_id"], "employee")
        _check_session_ownership(actor, row, role)

        if row["status"] == "completed":
            return {"status": "completed"}

        from interviewer import load_state, write_rollup
        state = await load_state(conn, str(session_id))
        if state:
            rollup = await write_rollup(conn, state)
        else:
            await conn.execute(
                "UPDATE interview_sessions SET status = 'completed', completed_at = now() WHERE id = $1",
                session_id,
            )
        return {"status": "completed"}


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

async def ws_interview(websocket: WebSocket, session_id: str, key: str):
    """WebSocket endpoint for live interview events."""
    _redacted = key[:4] + "***" if key else "***"
    log.info("WS connect session=%s key=%s", session_id, _redacted)

    try:
        actor = await _resolve_key(key)
    except Exception:
        log.warning("WS rejected: bad key for session=%s", session_id)
        await websocket.close(code=1008)
        return

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT project_id, employee_id FROM interview_sessions WHERE id = $1",
            session_id,
        )
        if row is None:
            await websocket.close(code=1008)
            return

        try:
            role = await check_access(conn, actor, row["project_id"], "employee")
            _check_session_ownership(actor, row, role)
        except HTTPException:
            await websocket.close(code=1008)
            return

    await websocket.accept()

    if session_id not in _ws_connections:
        _ws_connections[session_id] = []
    _ws_connections[session_id].append(websocket)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if session_id in _ws_connections:
            _ws_connections[session_id] = [
                ws for ws in _ws_connections[session_id] if ws != websocket
            ]


async def _ws_broadcast(session_id: str, event_type: str, data: dict):
    """Broadcast event to all WS connections for a session."""
    conns = _ws_connections.get(session_id, [])
    msg = json.dumps({"type": event_type, "data": data})
    dead = []
    for ws in conns:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        conns.remove(ws)


def _session_dict(row) -> dict:
    d = {
        "id": str(row["id"]),
        "project_id": row["project_id"],
        "employee_id": row["employee_id"],
        "topic": row["topic"],
        "status": row["status"],
    }
    if "planned_duration_min" in row.keys():
        d["planned_duration_min"] = row["planned_duration_min"]
    if "claims_extracted" in row.keys():
        d["claims_extracted"] = row["claims_extracted"]
    if "created_at" in row.keys():
        d["created_at"] = row["created_at"].isoformat() if row["created_at"] else None
    if "completed_at" in row.keys():
        d["completed_at"] = row["completed_at"].isoformat() if row["completed_at"] else None
    return d
