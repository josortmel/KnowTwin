"""Shared cursor-based pagination."""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException


async def paginate(conn, base_sql: str, params: list, limit: int,
                   cursor: str | None = None,
                   cursor_column: str = "created_at"):
    if cursor:
        try:
            params.append(datetime.fromisoformat(cursor))
        except (ValueError, TypeError):
            raise HTTPException(422, "invalid cursor format")
        base_sql += f" AND {cursor_column} < ${len(params)}"
    base_sql += f" ORDER BY {cursor_column} DESC LIMIT ${len(params)+1}"
    params.append(limit + 1)
    rows = await conn.fetch(base_sql, *params)
    has_next = len(rows) > limit
    items = rows[:limit]
    col_key = cursor_column.split(".")[-1]
    next_cursor = items[-1][col_key].isoformat() if has_next and items else None
    return items, next_cursor
