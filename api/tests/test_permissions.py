"""Permissions tests — ported from EcoDB, adapted for KnowTwin roles.

Tests check_access, role hierarchy, visibility helpers.
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql://knowtwin:knowtwin_test_pass@knowtwin-db:5432/knowtwin")
os.environ.setdefault("ENVIRONMENT", "development")

import asyncpg

from permissions import (
    check_access,
    _ROLE_RANK,
    no_null_bytes,
    validate_name_strip_blank,
)

_DB_URL = os.environ["DATABASE_URL"]


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_role_rank_ordering():
    assert _ROLE_RANK["consumer"] < _ROLE_RANK["employee"]
    assert _ROLE_RANK["employee"] < _ROLE_RANK["curator"]
    assert _ROLE_RANK["curator"] < _ROLE_RANK["admin"]


def test_no_null_bytes_rejects():
    with pytest.raises(ValueError, match="null bytes"):
        no_null_bytes("hello\x00world", "test_field")


def test_no_null_bytes_passes_clean():
    assert no_null_bytes("hello world", "test_field") == "hello world"


def test_validate_name_strips_and_rejects_blank():
    assert validate_name_strip_blank("  hello  ") == "hello"
    with pytest.raises(ValueError, match="blank"):
        validate_name_strip_blank("   ")
    with pytest.raises(ValueError, match="null bytes"):
        validate_name_strip_blank("hello\x00")


def test_check_access_super_bypass():
    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            actor = {"sub": "1", "is_super": True}
            role = await check_access(conn, actor, 1, "admin")
            assert role == "admin"
        finally:
            await conn.close()
    _run(_test())


def test_check_access_denies_non_member():
    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            actor = {"sub": "1", "is_super": False}
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc:
                await check_access(conn, actor, 99999, "consumer")
            assert exc.value.status_code == 403
        finally:
            await conn.close()
    _run(_test())


def test_check_access_enforces_minimum_role():
    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval("INSERT INTO users (name) VALUES ('tp_role') RETURNING id")
            await conn.execute(
                "INSERT INTO project_members (project_id, user_id, role) VALUES (1, $1, 'consumer')",
                uid,
            )
            actor = {"sub": str(uid), "is_super": False}

            role = await check_access(conn, actor, 1, "consumer")
            assert role == "consumer"

            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc:
                await check_access(conn, actor, 1, "curator")
            assert exc.value.status_code == 403

            await conn.execute("DELETE FROM project_members WHERE user_id = $1", uid)
            await conn.execute("DELETE FROM users WHERE id = $1", uid)
        finally:
            await conn.close()
    _run(_test())


def test_check_access_curator_passes_employee_gate():
    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval("INSERT INTO users (name) VALUES ('tp_curator') RETURNING id")
            await conn.execute(
                "INSERT INTO project_members (project_id, user_id, role) VALUES (1, $1, 'curator')",
                uid,
            )
            actor = {"sub": str(uid), "is_super": False}
            role = await check_access(conn, actor, 1, "employee")
            assert role == "curator"

            await conn.execute("DELETE FROM project_members WHERE user_id = $1", uid)
            await conn.execute("DELETE FROM users WHERE id = $1", uid)
        finally:
            await conn.close()
    _run(_test())
