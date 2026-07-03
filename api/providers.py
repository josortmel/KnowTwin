"""LLM provider keys CRUD — Memory Agent v1.3 (Spec §2).

API keys for LLM providers, encrypted at rest with Fernet. Plaintext keys are
never returned: GET masks as "sk-****...last4". Cell worker decrypts on read.
Auth: super-only for all operations.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field

import crypto
from auth import get_current_user
from db import get_pool

router = APIRouter(prefix="/providers", tags=["providers"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ProviderKeySummary(BaseModel):
    id: int
    provider: str
    api_key_masked: str
    model_default: Optional[str] = None
    display_name: Optional[str] = None
    created_at: datetime


class ProviderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(..., min_length=1, max_length=64, pattern="^[a-z0-9_]+$")
    api_key: str = Field(..., min_length=1, max_length=512)
    model_default: Optional[str] = Field(None, max_length=128)
    display_name: Optional[str] = Field(None, max_length=128)


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: Optional[str] = Field(None, min_length=1, max_length=512)
    model_default: Optional[str] = Field(None, max_length=128)
    display_name: Optional[str] = Field(None, max_length=128)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mask(plain: str) -> str:
    if len(plain) <= 4:
        return "****"
    return f"{plain[:3]}****...{plain[-4:]}"


def _to_summary(row) -> ProviderKeySummary:
    try:
        masked = _mask(crypto.decrypt(row["api_key_encrypted"]))
    except Exception as _dec_err:
        import logging
        logging.getLogger("ecodb.providers").warning(
            "failed to decrypt provider %s: %s", row["provider"], _dec_err)
        masked = "****"
    return ProviderKeySummary(
        id=row["id"],
        provider=row["provider"],
        api_key_masked=masked,
        model_default=row["model_default"],
        display_name=row["display_name"],
        created_at=row["created_at"],
    )


def _require_super(actor: dict) -> None:
    if not actor.get("is_super"):
        raise HTTPException(403, "provider key management requires super access")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_providers(actor: dict = Depends(get_current_user)) -> dict:
    _require_super(actor)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM llm_provider_keys ORDER BY provider")
    items = [_to_summary(r) for r in rows]
    return {"items": items, "total": len(items)}


@router.post("", status_code=201)
async def create_provider(
    body: ProviderCreate,
    actor: dict = Depends(get_current_user),
) -> ProviderKeySummary:
    _require_super(actor)
    encrypted = crypto.encrypt(body.api_key)
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO llm_provider_keys
                    (provider, api_key_encrypted, model_default, display_name, added_by)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
                """,
                body.provider, encrypted, body.model_default,
                body.display_name, int(actor["sub"]))
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, f"provider {body.provider!r} already exists")
    return _to_summary(row)


@router.put("/{provider_id}")
async def update_provider(
    body: ProviderUpdate,
    provider_id: int = Path(..., ge=1),
    actor: dict = Depends(get_current_user),
) -> ProviderKeySummary:
    _require_super(actor)
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(422, "no fields to update")
    if "api_key" in fields:
        fields["api_key_encrypted"] = crypto.encrypt(fields.pop("api_key"))
    pool = await get_pool()
    async with pool.acquire() as conn:
        if not await conn.fetchval(
                "SELECT 1 FROM llm_provider_keys WHERE id = $1", provider_id):
            raise HTTPException(404, f"provider {provider_id} not found")
        set_parts: list = []
        params: list = []
        for key, value in fields.items():
            params.append(value)
            set_parts.append(f"{key} = ${len(params)}")
        set_parts.append("updated_at = NOW()")
        params.append(provider_id)
        row = await conn.fetchrow(
            f"UPDATE llm_provider_keys SET {', '.join(set_parts)} "
            f"WHERE id = ${len(params)} RETURNING *",
            *params)
    return _to_summary(row)


_PROVIDER_MODELS: dict[str, list[str]] = {
    "deepseek": ["deepseek-chat", "deepseek-v4-flash", "deepseek-v4-pro", "deepseek-reasoner"],
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"],
    "anthropic": ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
}


@router.get("/{provider}/models")
async def list_provider_models(
    provider: str = Path(..., min_length=1),
    actor: dict = Depends(get_current_user),
) -> dict:
    _require_super(actor)
    models = _PROVIDER_MODELS.get(provider, [])
    return {"provider": provider, "models": models}


@router.delete("/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: int = Path(..., ge=1),
    actor: dict = Depends(get_current_user),
):
    _require_super(actor)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT provider FROM llm_provider_keys WHERE id = $1", provider_id)
        if row is None:
            raise HTTPException(404, f"provider {provider_id} not found")
        in_use = await conn.fetchval(
            "SELECT COUNT(*) FROM cell_task_configs WHERE provider = $1",
            row["provider"])
        if in_use:
            raise HTTPException(409, f"provider in use by {in_use} cell configs")
        await conn.execute(
            "DELETE FROM llm_provider_keys WHERE id = $1", provider_id)
