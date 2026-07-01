"""Prompt templates CRUD — Memory Agent v1.3 (Spec §2).

Reusable prompt texts for cell workers. Templates are global (not agent-scoped).
Auth: super-only for write, any authenticated user for read.
DELETE refuses (409) when a template is referenced by a cell config.
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

router = APIRouter(prefix="/cells/templates", tags=["cells"])


def _unique_violation_409(exc: asyncpg.UniqueViolationError) -> HTTPException:
    # idx_cell_prompt_templates_default enforces one default per cell_type;
    # cell_prompt_templates_name_key enforces unique name.
    if "default" in (getattr(exc, "constraint_name", "") or ""):
        return HTTPException(409, "a default template already exists for this cell_type")
    return HTTPException(409, "template name already exists")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class PromptTemplate(BaseModel):
    id: int
    name: str
    cell_type: str
    content: str
    is_default: bool
    created_at: datetime
    updated_at: datetime


class TemplateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=200)
    cell_type: str = Field(..., min_length=1, max_length=64)
    content: str = Field(..., min_length=1)
    is_default: bool = False


class TemplateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    cell_type: Optional[str] = Field(None, min_length=1, max_length=64)
    content: Optional[str] = Field(None, min_length=1)
    is_default: Optional[bool] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_templates(
    cell_type: Optional[str] = Query(None, min_length=1, max_length=64),
    actor: dict = Depends(get_current_user),
) -> dict:
    if not actor.get("is_super"):
        raise HTTPException(403, "template listing requires super access")
    pool = await get_pool()
    async with pool.acquire() as conn:
        if cell_type:
            rows = await conn.fetch(
                "SELECT * FROM cell_prompt_templates WHERE cell_type = $1 "
                "ORDER BY name", cell_type)
        else:
            rows = await conn.fetch(
                "SELECT * FROM cell_prompt_templates ORDER BY name")
    items = [PromptTemplate(**dict(r)) for r in rows]
    return {"items": items, "total": len(items)}


@router.post("", status_code=201)
async def create_template(
    body: TemplateCreate,
    actor: dict = Depends(get_current_user),
) -> PromptTemplate:
    if not actor.get("is_super"):
        raise HTTPException(403, "template write requires super access")
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO cell_prompt_templates
                    (name, cell_type, content, is_default, created_by)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
                """,
                body.name, body.cell_type, body.content, body.is_default,
                int(actor["sub"]))
        except asyncpg.UniqueViolationError as e:
            raise _unique_violation_409(e)
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details)
               VALUES ($1, 'create', 'cell_prompt_template', $2::text, $3::jsonb)""",
            int(actor["sub"]), str(row["id"]),
            json.dumps({"name": body.name, "cell_type": body.cell_type,
                        "is_default": body.is_default}))
    return PromptTemplate(**dict(row))


@router.put("/{template_id}")
async def update_template(
    body: TemplateUpdate,
    template_id: int = Path(..., ge=1),
    actor: dict = Depends(get_current_user),
) -> PromptTemplate:
    if not actor.get("is_super"):
        raise HTTPException(403, "template write requires super access")
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(422, "no fields to update")
    pool = await get_pool()
    async with pool.acquire() as conn:
        if not await conn.fetchval(
                "SELECT 1 FROM cell_prompt_templates WHERE id = $1", template_id):
            raise HTTPException(404, f"template {template_id} not found")
        set_parts: list = []
        params: list = []
        for key, value in fields.items():
            params.append(value)
            set_parts.append(f"{key} = ${len(params)}")
        set_parts.append("updated_at = NOW()")
        params.append(template_id)
        try:
            row = await conn.fetchrow(
                f"UPDATE cell_prompt_templates SET {', '.join(set_parts)} "
                f"WHERE id = ${len(params)} RETURNING *",
                *params)
        except asyncpg.UniqueViolationError as e:
            raise _unique_violation_409(e)
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details)
               VALUES ($1, 'update', 'cell_prompt_template', $2::text, $3::jsonb)""",
            int(actor["sub"]), str(template_id),
            json.dumps({"fields_changed": list(fields.keys())}))
    return PromptTemplate(**dict(row))


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: int = Path(..., ge=1),
    actor: dict = Depends(get_current_user),
):
    if not actor.get("is_super"):
        raise HTTPException(403, "template write requires super access")
    pool = await get_pool()
    async with pool.acquire() as conn:
        if not await conn.fetchval(
                "SELECT 1 FROM cell_prompt_templates WHERE id = $1", template_id):
            raise HTTPException(404, f"template {template_id} not found")
        in_use = await conn.fetchval(
            "SELECT COUNT(*) FROM cell_task_configs WHERE prompt_template_id = $1",
            template_id)
        if in_use:
            raise HTTPException(409, f"template referenced by {in_use} configs")
        name = await conn.fetchval(
            "SELECT name FROM cell_prompt_templates WHERE id = $1", template_id)
        await conn.execute(
            "DELETE FROM cell_prompt_templates WHERE id = $1", template_id)
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details)
               VALUES ($1, 'delete', 'cell_prompt_template', $2::text, $3::jsonb)""",
            int(actor["sub"]), str(template_id),
            json.dumps({"name": name}))
