"""KnowTwin per-project settings — sanitization defaults + retention policy."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user
from db import get_pool
from permissions import check_access

log = logging.getLogger("knowtwin.org_settings")

router = APIRouter(prefix="/projects", tags=["settings"])

_VALID_SENSITIVITIES = frozenset({"public", "team", "restricted"})


class SettingsPayload(BaseModel):
    sanitization_defaults: Optional[dict[str, Any]] = None
    retention: Optional[dict] = None


@router.get("/{project_id}/settings")
async def get_settings(
    project_id: int,
    actor: dict = Depends(get_current_user),
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await check_access(conn, actor, project_id, "curator")
        row = await conn.fetchrow(
            "SELECT config FROM org_settings WHERE project_id = $1", project_id
        )
        if row is None:
            return {"project_id": project_id, "config": {}}
        config = row["config"]
        if isinstance(config, str):
            config = json.loads(config)
        return {"project_id": project_id, "config": config}


@router.put("/{project_id}/settings")
async def put_settings(
    project_id: int,
    body: SettingsPayload,
    actor: dict = Depends(get_current_user),
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await check_access(conn, actor, project_id, "admin")

        proj = await conn.fetchval("SELECT id FROM projects WHERE id = $1", project_id)
        if proj is None:
            raise HTTPException(404, "project not found")

        if body.sanitization_defaults:
            for etype, val in body.sanitization_defaults.items():
                if isinstance(val, str):
                    if val not in _VALID_SENSITIVITIES:
                        raise HTTPException(422, f"invalid sensitivity '{val}' for type '{etype}'")
                elif isinstance(val, dict):
                    ds = val.get("default_sensitivity")
                    if ds and ds not in _VALID_SENSITIVITIES:
                        raise HTTPException(422, f"invalid sensitivity '{ds}' for type '{etype}'")
                    kw = val.get("judgment_keywords")
                    if kw is not None and not isinstance(kw, list):
                        raise HTTPException(422, f"judgment_keywords must be a list for type '{etype}'")
                else:
                    raise HTTPException(422, f"invalid value for type '{etype}': must be string or object")

        existing = await conn.fetchval(
            "SELECT config FROM org_settings WHERE project_id = $1", project_id
        )
        config: dict = json.loads(existing) if existing else {}
        if body.sanitization_defaults is not None:
            config["sanitization_defaults"] = body.sanitization_defaults
        if body.retention is not None:
            config["retention"] = body.retention

        await conn.execute(
            """
            INSERT INTO org_settings (project_id, config)
            VALUES ($1, $2::jsonb)
            ON CONFLICT (project_id) DO UPDATE SET config = $2::jsonb
            """,
            project_id, json.dumps(config),
        )
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'update_settings', 'org_settings', $2, $3::jsonb, $4)""",
            int(actor["sub"]), str(project_id),
            json.dumps(config),
            actor.get("organization_id"),
        )
        return {"project_id": project_id, "config": config}


async def get_sanitization_default(conn, project_id: int, entity_type: str) -> Optional[str]:
    """Look up the default sensitivity for an entity type from org_settings."""
    row = await conn.fetchrow(
        "SELECT config FROM org_settings WHERE project_id = $1", project_id
    )
    if row is None:
        return None
    config = row["config"]
    if isinstance(config, str):
        config = json.loads(config)
    defaults = config.get("sanitization_defaults")
    if not defaults or not isinstance(defaults, dict):
        return None
    val = defaults.get(entity_type)
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return val.get("default_sensitivity")
    return None
