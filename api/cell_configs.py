"""Cell task configs CRUD — Memory Agent v1.3 (Spec §2).

Per-agent, per-cell-type, per-level configuration for the metacognition cells.
Auth: super-only for write (POST/PUT/DELETE), super-or-owner for read (GET).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from auth import get_current_user
from db import get_pool
from permissions import resolve_agent_for_actor

router = APIRouter(prefix="/cells/configs", tags=["cells"])

_LEVEL_PATTERN = "^(weekly|monthly|quarterly|yearly)$"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CellTaskConfig(BaseModel):
    id: int
    agent_id: int
    agent_identifier: str
    cell_type: str
    enabled: bool
    model: str
    provider: str
    prompt_template_id: Optional[int] = None
    prompt_template_name: Optional[str] = None
    schedule_cron: Optional[str] = None
    level: Optional[str] = None
    config: dict = Field(default_factory=dict)
    last_run: Optional[datetime] = None
    last_run_status: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CellConfigCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_identifier: str = Field(..., min_length=1, max_length=200)
    cell_type: str = Field(..., min_length=1, max_length=64, pattern="^[a-z0-9_]+$")
    enabled: bool = True
    model: str = Field("deepseek-chat", min_length=1, max_length=128)
    provider: str = Field("deepseek", min_length=1, max_length=64, pattern="^[a-z0-9_]+$")
    prompt_template_id: Optional[int] = None
    schedule_cron: Optional[str] = Field(None, max_length=128)
    level: Optional[str] = Field(None, pattern=_LEVEL_PATTERN)
    config: dict = Field(default_factory=dict)


class CellConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cell_type: Optional[str] = Field(None, min_length=1, max_length=64, pattern="^[a-z0-9_]+$")
    enabled: Optional[bool] = None
    model: Optional[str] = Field(None, min_length=1, max_length=128)
    provider: Optional[str] = Field(None, min_length=1, max_length=64, pattern="^[a-z0-9_]+$")
    prompt_template_id: Optional[int] = None
    schedule_cron: Optional[str] = Field(None, max_length=128)
    level: Optional[str] = Field(None, pattern=_LEVEL_PATTERN)
    config: Optional[dict] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_jsonb(val):
    if val is None:
        return {}
    if isinstance(val, str):
        return json.loads(val)
    return val


_MIN_CRON_INTERVAL_MINUTES = 15


def _validate_cron(expr: Optional[str]) -> None:
    if expr is None:
        return
    from datetime import datetime, timedelta, timezone
    from croniter import croniter
    if not croniter.is_valid(expr):
        raise HTTPException(422, f"invalid cron expression: {expr!r}")
    # Floor on frequency: prevent accidental cell storms (e.g. "* * * * *") that
    # saturate the asyncpg pool and trigger stuck-run cascades (VS_L4_4).
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    itr = croniter(expr, base)
    t1 = itr.get_next(datetime)
    t2 = itr.get_next(datetime)
    if t2 - t1 < timedelta(minutes=_MIN_CRON_INTERVAL_MINUTES):
        raise HTTPException(
            422, f"cron fires more often than every {_MIN_CRON_INTERVAL_MINUTES} minutes — "
                 f"too frequent for a cell task (would saturate the LLM/DB pool)")


def _to_config(row) -> CellTaskConfig:
    return CellTaskConfig(
        id=row["id"],
        agent_id=row["agent_id"],
        agent_identifier=row["agent_identifier"],
        cell_type=row["cell_type"],
        enabled=row["enabled"],
        model=row["model"],
        provider=row["provider"],
        prompt_template_id=row["prompt_template_id"],
        prompt_template_name=row.get("prompt_template_name"),
        schedule_cron=row["schedule_cron"],
        level=row["level"],
        config=_parse_jsonb(row["config"]),
        last_run=row.get("last_run"),
        last_run_status=row.get("last_run_status"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


_SELECT = """
    SELECT ctc.*, a.identifier AS agent_identifier,
           cpt.name AS prompt_template_name,
           lr.finished_at AS last_run, lr.status AS last_run_status
    FROM cell_task_configs ctc
    JOIN agents a ON a.id = ctc.agent_id
    LEFT JOIN cell_prompt_templates cpt ON cpt.id = ctc.prompt_template_id
    -- last_run is per (agent, cell_type), NOT per level: cell_runs has no level
    -- column, so weekly/monthly/quarterly/yearly consolidation configs for the
    -- same agent all surface the same most-recent consolidation run (IC1, accepted).
    LEFT JOIN LATERAL (
        SELECT finished_at, status FROM cell_runs cr
        WHERE cr.agent_id = ctc.agent_id AND cr.cell_type = ctc.cell_type
        ORDER BY cr.started_at DESC LIMIT 1
    ) lr ON true
"""


async def _fetch_config(conn, config_id: int) -> CellTaskConfig:
    row = await conn.fetchrow(_SELECT + " WHERE ctc.id = $1", config_id)
    if row is None:
        raise HTTPException(404, f"config {config_id} not found")
    return _to_config(row)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_configs(
    agent_identifier: Optional[str] = Query(None, min_length=1, max_length=200),
    cell_type: Optional[str] = Query(None, min_length=1, max_length=64),
    enabled: Optional[bool] = Query(None),
    actor: dict = Depends(get_current_user),
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        conditions = ["1=1"]
        params: list = []
        if agent_identifier:
            agent = await resolve_agent_for_actor(conn, actor, agent_identifier)
            params.append(agent["id"])
            conditions.append(f"ctc.agent_id = ${len(params)}")
        elif not actor.get("is_super"):
            params.append(int(actor["sub"]))
            conditions.append(f"a.user_id = ${len(params)}")
        if cell_type:
            params.append(cell_type)
            conditions.append(f"ctc.cell_type = ${len(params)}")
        if enabled is not None:
            params.append(enabled)
            conditions.append(f"ctc.enabled = ${len(params)}")
        where = " AND ".join(conditions)
        rows = await conn.fetch(
            _SELECT + f" WHERE {where} ORDER BY a.identifier, ctc.cell_type, ctc.level",
            *params)
    items = [_to_config(r) for r in rows]
    return {"items": items, "total": len(items)}


@router.post("", status_code=201)
async def create_config(
    body: CellConfigCreate,
    actor: dict = Depends(get_current_user),
) -> CellTaskConfig:
    if not actor.get("is_super"):
        raise HTTPException(403, "cell config write requires super access")
    _validate_cron(body.schedule_cron)
    pool = await get_pool()
    async with pool.acquire() as conn:
        agent = await resolve_agent_for_actor(conn, actor, body.agent_identifier)
        try:
            new_id = await conn.fetchval(
                """
                INSERT INTO cell_task_configs
                    (agent_id, cell_type, enabled, model, provider,
                     prompt_template_id, schedule_cron, level, config)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                RETURNING id
                """,
                agent["id"], body.cell_type, body.enabled, body.model,
                body.provider, body.prompt_template_id, body.schedule_cron,
                body.level, json.dumps(body.config),
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(
                409,
                f"config already exists for agent={body.agent_identifier} "
                f"cell_type={body.cell_type} level={body.level}")
        except asyncpg.ForeignKeyViolationError:
            raise HTTPException(
                422, f"prompt_template_id {body.prompt_template_id} not found")
        result = await _fetch_config(conn, new_id)
    return result


@router.put("/{config_id}")
async def update_config(
    body: CellConfigUpdate,
    config_id: int = Path(..., ge=1),
    actor: dict = Depends(get_current_user),
) -> CellTaskConfig:
    if not actor.get("is_super"):
        raise HTTPException(403, "cell config write requires super access")
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(422, "no fields to update")
    if "schedule_cron" in fields:
        _validate_cron(fields["schedule_cron"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        if not await conn.fetchval(
                "SELECT 1 FROM cell_task_configs WHERE id = $1", config_id):
            raise HTTPException(404, f"config {config_id} not found")
        set_parts: list = []
        params: list = []
        for key, value in fields.items():
            params.append(json.dumps(value) if key == "config" else value)
            cast = "::jsonb" if key == "config" else ""
            set_parts.append(f"{key} = ${len(params)}{cast}")
        set_parts.append("updated_at = NOW()")
        params.append(config_id)
        try:
            await conn.execute(
                f"UPDATE cell_task_configs SET {', '.join(set_parts)} "
                f"WHERE id = ${len(params)}",
                *params)
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "config update violates uniqueness "
                                     "(agent+cell_type+level)")
        except asyncpg.ForeignKeyViolationError:
            raise HTTPException(422, "prompt_template_id not found")
        result = await _fetch_config(conn, config_id)
    return result


@router.post("/{config_id}/reset")
async def reset_config(
    config_id: int = Path(..., ge=1),
    actor: dict = Depends(get_current_user),
) -> CellTaskConfig:
    """Reset config + prompt to seeded defaults."""
    if not actor.get("is_super"):
        raise HTTPException(403, "cell config write requires super access")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, default_config, default_prompt_content, prompt_template_id "
            "FROM cell_task_configs WHERE id = $1", config_id)
        if row is None:
            raise HTTPException(404, f"config {config_id} not found")
        if row["default_config"] is None:
            raise HTTPException(409, "no defaults stored for this config")

        defaults = _parse_jsonb(row["default_config"])
        set_parts = ["config = $1::jsonb", "updated_at = NOW()"]
        params: list = [json.dumps(defaults)]
        for k in ("model", "provider", "enabled"):
            if k in defaults:
                params.append(defaults[k])
                set_parts.append(f"{k} = ${len(params)}")
        params.append(config_id)
        await conn.execute(
            f"UPDATE cell_task_configs SET {', '.join(set_parts)} WHERE id = ${len(params)}",
            *params)

        if row["default_prompt_content"] and row["prompt_template_id"]:
            await conn.execute(
                "UPDATE cell_prompt_templates SET content = $1, updated_at = NOW() WHERE id = $2",
                row["default_prompt_content"], row["prompt_template_id"])

        await conn.execute(
            "INSERT INTO audit_log (user_id, action, resource, resource_id, details) "
            "VALUES ($1, 'reset_config', 'cell_task_config', $2::text, '{}'::jsonb)",
            int(actor["sub"]), str(config_id))

        return await _fetch_config(conn, config_id)


@router.delete("/{config_id}", status_code=204)
async def delete_config(
    config_id: int = Path(..., ge=1),
    actor: dict = Depends(get_current_user),
):
    if not actor.get("is_super"):
        raise HTTPException(403, "cell config write requires super access")
    pool = await get_pool()
    async with pool.acquire() as conn:
        deleted = await conn.fetchval(
            "DELETE FROM cell_task_configs WHERE id = $1 RETURNING id", config_id)
    if deleted is None:
        raise HTTPException(404, f"config {config_id} not found")
