"""Pool de conexiones asyncpg al PostgreSQL.

Convencion de uso desde endpoints:

    from db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT ...")

El pool se crea perezosamente al primer acquire (lifecycle del API). En tests
con TestClient se puede inyectar un pool propio via override_pool().
"""
from __future__ import annotations

from typing import Optional

import asyncpg

import settings

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    """Devuelve el pool global, creandolo en el primer acquire."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.DATABASE_URL,
            min_size=settings.DB_POOL_MIN,
            max_size=settings.DB_POOL_MAX,
            command_timeout=settings.DB_COMMAND_TIMEOUT,
        )
    return _pool


async def close_pool() -> None:
    """Cierra el pool al apagar el servicio (lifespan event)."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def override_pool(pool: Optional[asyncpg.Pool]) -> None:
    """Inyectar un pool ad-hoc (uso en tests). Pasar None para restaurar el lazy."""
    global _pool
    _pool = pool
