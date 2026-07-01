"""P1.22 Demo seed e2e verification — asserts on final demo state.

Run AFTER scripts/seed_demo.py has been executed.
  docker exec knowtwin-api python -m pytest tests/test_demo_seed_e2e.py -v
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
from fastapi.testclient import TestClient

from main import create_app
from auth import generate_api_key

_DB_URL = os.environ["DATABASE_URL"]
_PID = 1


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _dbval(sql, *args):
    conn = await asyncpg.connect(_DB_URL)
    try:
        return await conn.fetchval(sql, *args)
    finally:
        await conn.close()


async def _dbrows(sql, *args):
    conn = await asyncpg.connect(_DB_URL)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


@pytest.fixture(scope="module")
def client():
    app = create_app("development")
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin_key():
    async def _setup():
        conn = await asyncpg.connect(_DB_URL)
        try:
            kp, kh = generate_api_key()
            await conn.execute(
                "INSERT INTO api_keys (key_hash, name, user_id, active) "
                "VALUES ($1, 'demo_test_key', 1, true) ON CONFLICT DO NOTHING",
                kh,
            )
            return kp
        finally:
            await conn.close()

    key = _run(_setup())
    yield key

    _run(_dbval("DELETE FROM api_keys WHERE name = 'demo_test_key'"))


def test_demo_claims_exist():
    """Demo has claims from both documents and interviews."""
    total = _run(_dbval(
        "SELECT COUNT(*) FROM claims WHERE project_id = $1 AND source_type = 'seed_demo'", _PID
    ))
    doc_count = _run(_dbval(
        "SELECT COUNT(*) FROM claims WHERE project_id = $1 AND source_type = 'seed_demo' AND session_id IS NULL", _PID
    ))
    tacit_count = _run(_dbval(
        "SELECT COUNT(*) FROM claims WHERE project_id = $1 AND source_type = 'seed_demo' AND session_id IS NOT NULL", _PID
    ))
    assert doc_count >= 5, f"expected ≥5 doc claims, got {doc_count}"
    assert tacit_count >= 4, f"expected ≥4 tacit claims, got {tacit_count}"


def test_star_tacit_claims_present():
    """5 star tacit claims are present (from interviews, absent from docs)."""
    star_subjects = ["Banco Norte", "ETL Pipeline", "CloudBase", "Nova Consulting"]
    for subj in star_subjects:
        count = _run(_dbval(
            "SELECT COUNT(*) FROM claims WHERE project_id = $1 AND subject_entity = $2 "
            "AND source_type = 'seed_demo' AND session_id IS NOT NULL",
            _PID, subj,
        ))
        assert count >= 1, f"missing tacit claim for {subj}"


def test_entities_seeded():
    """Entity dictionary has demo entities."""
    count = _run(_dbval("SELECT COUNT(*) FROM entity_dictionary"))
    assert count >= 50, f"expected ≥50 entities, got {count}"


def test_coverage_view_works():
    """entity_coverage view returns rows for project."""
    rows = _run(_dbrows(
        "SELECT entity_name, coverage_state FROM entity_coverage WHERE project_id = $1 LIMIT 5",
        _PID,
    ))
    assert len(rows) > 0, "coverage view should return rows"


def test_twin_insufficient_info(client, admin_key):
    """Out-of-scope query returns insufficient information."""
    resp = client.post("/twin/query", json={
        "question": "zxqwj9k7m3p2 completely unrelated nonsense",
        "project_id": _PID,
    }, headers={"Authorization": f"Bearer {admin_key}"})
    assert resp.status_code == 200
    answer = resp.json()["answer"].lower()
    assert "insufficient" in answer or len(resp.json()["sources"]) == 0
