"""Endpoints user_preferences -- .13.

Preferencias de UI por user (tema, layout, filtros guardados, etc.). Estructura
designed for the frontend dashboard -- no hardcodeamos keys aqui.
Almacenadas como JSONB en `user_preferences` (schema init.sql:514).

Endpoints:
- GET /users/me/preferences   leer preferencias del actor. {} si no hay row.
- PUT /users/me/preferences   replace completo del JSONB. Upsert.

Permisos: solo el propio user puede leer/modificar SUS preferences. El endpoint
/me lo asume implicito (actor.sub). NO hay endpoint para que admin lea/escriba
preferencias de otros -- innecesario en single-tenant mode; en fork multi-tenant
anadir si surge caso.

Validacion tamano: max 32KB JSON request body para evitar DoS via prefs grandes.
JSONB en Postgres puede llegar hasta 1GB pero lo limitamos a tamano razonable.
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from auth import get_current_user
from db import get_pool


# Tamano max del JSONB serialized -- DoS prevention.
MAX_PREFS_SIZE = 32_000  # 32KB de JSON razonable para preferencias UI


router = APIRouter(prefix="/users/me", tags=["users"])


class PreferencesResponse(BaseModel):
    user_id: int
    prefs: dict
    updated_at: datetime | None


class PreferencesUpdate(BaseModel):
    """Full JSONB replacement. Arbitrary keys allowed inside prefs dict.
    The body envelope rejects unknown fields to prevent silent drift.
    """

    model_config = ConfigDict(extra="forbid")
    prefs: dict = Field(..., description="Complete dictionary of UI preferences.")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/preferences", response_model=PreferencesResponse)
async def get_my_preferences(
    actor: dict = Depends(get_current_user),
) -> PreferencesResponse:
    """Devuelve las preferencias del actor. Si no hay row en user_preferences,
    devuelve prefs={} sin crear row (lazy creation en PUT)."""
    user_id = int(actor["sub"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, prefs, updated_at FROM user_preferences WHERE user_id = $1",
            user_id,
        )
    if row is None:
        return PreferencesResponse(user_id=user_id, prefs={}, updated_at=None)
    # asyncpg devuelve JSONB como string en algunos paths -- manejar ambos.
    prefs = row["prefs"]
    if isinstance(prefs, str):
        prefs = json.loads(prefs)
    return PreferencesResponse(
        user_id=row["user_id"],
        prefs=prefs,
        updated_at=row["updated_at"],
    )


@router.put("/preferences", response_model=PreferencesResponse)
async def put_my_preferences(
    body: PreferencesUpdate,
    actor: dict = Depends(get_current_user),
) -> PreferencesResponse:
    """Replace completo del JSONB. Upsert (INSERT ON CONFLICT UPDATE).

    Validacion tamano: si el JSON serializado pasa MAX_PREFS_SIZE, 422.
    Reason: prevent DoS via large prefs. PostgreSQL would accept up to 1 GB but
    that makes no sense for UI preferences.
    """
    serialized = json.dumps(body.prefs)
    if len(serialized.encode("utf-8")) > MAX_PREFS_SIZE:
        raise HTTPException(
            422,
            f"preferences exceeds {MAX_PREFS_SIZE} bytes -- keep UI prefs under 32KB",
        )

    user_id = int(actor["sub"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO user_preferences (user_id, prefs, updated_at)
            VALUES ($1, $2::jsonb, now())
            ON CONFLICT (user_id) DO UPDATE
              SET prefs = EXCLUDED.prefs, updated_at = now()
            RETURNING user_id, prefs, updated_at
            """,
            user_id, serialized,
        )
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'update_preferences', 'user_preferences', $2, $3::jsonb, $4)""",
            user_id, str(user_id),
            json.dumps({"size_bytes": len(serialized.encode("utf-8"))}),
            actor.get("organization_id"),
        )
    prefs = row["prefs"]
    if isinstance(prefs, str):
        prefs = json.loads(prefs)
    return PreferencesResponse(
        user_id=row["user_id"],
        prefs=prefs,
        updated_at=row["updated_at"],
    )
