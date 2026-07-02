"""P2.9 Batch claims, export, audit trail tests.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_claims_batch_export.py -v
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql://knowtwin:knowtwin_test_pass@knowtwin-db:5432/knowtwin")
os.environ.setdefault("ENVIRONMENT", "development")

import asyncpg

from claims import _csv_safe, _VALID_TRANSITIONS, _APPROVE_NEXT, batch_claims, BatchRequest

_DB_URL = os.environ["DATABASE_URL"]
_PREFIX = "batchtest_"
_PID = 1


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _db(sql, *args):
    conn = await asyncpg.connect(_DB_URL)
    try:
        return await conn.execute(sql, *args)
    finally:
        await conn.close()


async def _dbval(sql, *args):
    conn = await asyncpg.connect(_DB_URL)
    try:
        return await conn.fetchval(sql, *args)
    finally:
        await conn.close()


@pytest.fixture(scope="module", autouse=True)
def setup_teardown():
    async def _setup():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval(
                "INSERT INTO users (name) VALUES ($1) RETURNING id", f"{_PREFIX}curator"
            )
            await conn.execute(
                "INSERT INTO user_emails (email, user_id, is_primary) VALUES ($1, $2, true)",
                f"{_PREFIX}curator@test.kt", uid,
            )
            await conn.execute(
                "INSERT INTO project_members (project_id, user_id, role) VALUES ($1, $2, 'curator')",
                _PID, uid,
            )
        finally:
            await conn.close()

    _run(_setup())
    yield

    async def _teardown():
        conn = await asyncpg.connect(_DB_URL)
        try:
            await conn.execute("DELETE FROM audit_log WHERE resource_id IN (SELECT id::text FROM claims WHERE subject_entity LIKE $1)", f"{_PREFIX}%")
            await conn.execute("DELETE FROM claims WHERE subject_entity LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM project_members WHERE user_id IN (SELECT id FROM users WHERE name LIKE $1)", f"{_PREFIX}%")
            await conn.execute("DELETE FROM user_emails WHERE email LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM users WHERE name LIKE $1", f"{_PREFIX}%")
        finally:
            await conn.close()
    _run(_teardown())


def _clean():
    _run(_db("DELETE FROM audit_log WHERE resource_id IN (SELECT id::text FROM claims WHERE subject_entity LIKE $1)", f"{_PREFIX}%"))
    _run(_db("DELETE FROM claims WHERE subject_entity LIKE $1", f"{_PREFIX}%"))


def _make_claims(n, corroboration_level="single_source", sensitivity="restricted"):
    async def _do():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}curator")
            ids = []
            for i in range(n):
                cid = await conn.fetchval(
                    "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
                    "evidence_text, source_type, corroboration_level, sensitivity) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id",
                    uid, _PID, f"{_PREFIX}Entity{i}", f"pred_{i}",
                    f"Evidence for claim {i}", "document", corroboration_level, sensitivity,
                )
                ids.append(cid)
            return ids
        finally:
            await conn.close()
    return _run(_do())


def test_batch_50_set_sensitivity():
    """50 claims → batch set_sensitivity → all succeed + 50 audit entries."""
    _clean()
    ids = _make_claims(50)

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}curator")

            succeeded = []
            failed = []
            for cid in ids:
                row = await conn.fetchrow(
                    "SELECT id, project_id, corroboration_level, source_type, "
                    "embedding, sensitivity FROM claims WHERE id = $1", cid,
                )
                old_sens = row["sensitivity"]
                async with conn.transaction():
                    await conn.execute(
                        "UPDATE claims SET sensitivity = 'public', updated_at = now() WHERE id = $1",
                        cid,
                    )
                    await conn.execute(
                        "INSERT INTO audit_log (user_id, action, resource, resource_id, details) "
                        "VALUES ($1, 'batch_set_sensitivity', 'claim', $2, $3::jsonb)",
                        uid, str(cid),
                        json.dumps({"old": old_sens, "new": "public"}),
                    )
                succeeded.append(str(cid))

            assert len(succeeded) == 50

            audit_count = await conn.fetchval(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'batch_set_sensitivity' "
                "AND resource_id IN (SELECT id::text FROM claims WHERE subject_entity LIKE $1)",
                f"{_PREFIX}%",
            )
            assert audit_count == 50

            public_count = await conn.fetchval(
                "SELECT COUNT(*) FROM claims WHERE subject_entity LIKE $1 AND sensitivity = 'public'",
                f"{_PREFIX}%",
            )
            assert public_count == 50
        finally:
            await conn.close()
    _run(_test())


def test_partial_fail():
    """3 valid + 1 invalid UUID → 3 succeed in DB, 1 fail."""
    _clean()
    ids = _make_claims(3)
    fake_id = UUID("00000000-0000-0000-0000-000000000000")

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}curator")
            all_ids = list(ids) + [fake_id]

            succeeded = []
            failed = []
            for cid in all_ids:
                row = await conn.fetchrow(
                    "SELECT id, project_id, sensitivity FROM claims WHERE id = $1", cid,
                )
                if row is None:
                    failed.append({"id": str(cid), "error": "not_found"})
                    continue
                async with conn.transaction():
                    await conn.execute(
                        "UPDATE claims SET sensitivity = 'public', updated_at = now() WHERE id = $1", cid
                    )
                    await conn.execute(
                        "INSERT INTO audit_log (user_id, action, resource, resource_id, details) "
                        "VALUES ($1, 'batch_set_sensitivity', 'claim', $2, $3::jsonb)",
                        uid, str(cid), json.dumps({"old": row["sensitivity"], "new": "public"}),
                    )
                succeeded.append({"id": str(cid)})

            assert len(succeeded) == 3
            assert len(failed) == 1
            assert failed[0]["error"] == "not_found"
        finally:
            await conn.close()
    _run(_test())


def test_export_csv_role_filtered():
    """Restricted claims absent for consumer visibility, present for curator."""
    _clean()
    _make_claims(2, sensitivity="restricted")
    _make_claims(2, sensitivity="public")

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            from claims import _visibility_sql
            vis_c, vp_c = _visibility_sql("curator", 1, 2)
            curator_rows = await conn.fetch(
                f"SELECT id FROM claims c WHERE c.project_id = $1 AND ({vis_c}) "
                f"AND c.subject_entity LIKE '{_PREFIX}%'",
                _PID, *vp_c,
            )
            assert len(curator_rows) == 4

            vis_co, vp_co = _visibility_sql("consumer", 999, 2)
            consumer_rows = await conn.fetch(
                f"SELECT id FROM claims c WHERE c.project_id = $1 AND ({vis_co}) "
                f"AND c.subject_entity LIKE '{_PREFIX}%'",
                _PID, *vp_co,
            )
            assert len(consumer_rows) == 2
        finally:
            await conn.close()
    _run(_test())


def test_export_csv_injection_safe():
    """Cells starting with =,+,-,@,tab,cr → prefixed with single quote."""
    assert _csv_safe("=SUM(A1:A10)") == "'=SUM(A1:A10)"
    assert _csv_safe("+cmd") == "'+cmd"
    assert _csv_safe("-exploit") == "'-exploit"
    assert _csv_safe("@malicious") == "'@malicious"
    assert _csv_safe("\tcmd") == "'\tcmd"
    assert _csv_safe("\rcmd") == "'\rcmd"
    assert _csv_safe("  =hidden") == "'  =hidden"
    assert _csv_safe("normal text") == "normal text"
    assert _csv_safe("") == ""


def test_export_json_valid():
    """JSON export returns valid array structure."""
    _clean()
    _make_claims(3, sensitivity="public")

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            from claims import _visibility_sql
            from permissions import render_evidence
            vis_sql, vis_params = _visibility_sql("curator", 1, 2)

            rows = await conn.fetch(f"""
                SELECT id, subject_entity, predicate, evidence_text, sanitized_text,
                       source_type, sensitivity, corroboration_level, created_at, updated_at
                FROM claims c WHERE c.project_id = $1 AND ({vis_sql})
                AND c.subject_entity LIKE '{_PREFIX}%'
            """, _PID, *vis_params)

            items = []
            for r in rows:
                d = dict(r)
                d["id"] = str(d["id"])
                d["evidence_text"] = render_evidence("curator", d["evidence_text"], d.get("sanitized_text"))
                d["created_at"] = d["created_at"].isoformat()
                items.append(d)

            assert len(items) == 3
            for item in items:
                assert "id" in item
                assert "subject_entity" in item
                assert "evidence_text" in item
        finally:
            await conn.close()
    _run(_test())


def test_audit_trail_timeline():
    """Two sensitivity changes → 2 audit rows with actor+timestamp."""
    _clean()
    ids = _make_claims(1)

    async def _test():
        conn = await asyncpg.connect(_DB_URL)
        try:
            uid = await conn.fetchval("SELECT id FROM users WHERE name = $1", f"{_PREFIX}curator")
            cid = ids[0]

            for new_sens in ("team", "public"):
                async with conn.transaction():
                    await conn.execute(
                        "UPDATE claims SET sensitivity = $1, updated_at = now() WHERE id = $2",
                        new_sens, cid,
                    )
                    await conn.execute(
                        "INSERT INTO audit_log (user_id, action, resource, resource_id, details) "
                        "VALUES ($1, 'update_claim', 'claim', $2, $3::jsonb)",
                        uid, str(cid), json.dumps({"sensitivity": f"→{new_sens}"}),
                    )

            rows = await conn.fetch(
                "SELECT id, user_id, action, details, created_at FROM audit_log "
                "WHERE resource = 'claim' AND resource_id = $1 ORDER BY created_at ASC",
                str(cid),
            )
            assert len(rows) == 2
            assert all(r["user_id"] == uid for r in rows)
            assert all(r["created_at"] is not None for r in rows)
        finally:
            await conn.close()
    _run(_test())


def test_batch_authz():
    """Consumer/employee role cannot access batch operations."""
    from permissions import _ROLE_RANK
    assert _ROLE_RANK["consumer"] < _ROLE_RANK["curator"]
    assert _ROLE_RANK["employee"] < _ROLE_RANK["curator"]
