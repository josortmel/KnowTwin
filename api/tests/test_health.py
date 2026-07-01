"""Tests — health check + security headers + docs gating.

Ported from EcoDB, adapted for KnowTwin.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql://knowtwin:knowtwin_test_pass@knowtwin-db:5432/knowtwin")
os.environ.setdefault("ENVIRONMENT", "development")

import pytest
from fastapi.testclient import TestClient
from main import create_app
from settings import API_VERSION, DATABASE_URL, SCHEMA_VERSION

app_prod = create_app("production")
app_dev = create_app("development")
client_prod = TestClient(app_prod)
client_dev = TestClient(app_dev)


def test_get_health_returns_200():
    assert client_prod.get("/health").status_code == 200


def test_head_health_returns_200():
    assert client_prod.head("/health").status_code == 200


def test_health_returns_json():
    assert client_prod.get("/health").headers["content-type"].startswith("application/json")


def test_health_status_ok():
    assert client_prod.get("/health").json()["status"] == "ok"


def test_health_includes_service_metadata():
    payload = client_prod.get("/health").json()
    assert payload["service"] == "knowtwin-api"
    assert payload["api_version"] == API_VERSION
    assert payload["schema_version_target"] == SCHEMA_VERSION


def test_health_no_required_auth():
    assert client_prod.get("/health").status_code == 200


def test_security_headers_present():
    response = client_prod.get("/health")
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("referrer-policy") == "no-referrer"


def test_docs_hidden_in_production():
    assert client_prod.get("/docs").status_code == 404
    assert client_prod.get("/openapi.json").status_code == 404
    assert client_prod.get("/redoc").status_code == 404


def test_docs_available_in_development():
    assert client_dev.get("/docs").status_code == 200
    assert client_dev.get("/redoc").status_code == 200
    assert client_dev.get("/openapi.json").status_code == 200


def test_openapi_schema_in_development_describes_health():
    schema = client_dev.get("/openapi.json").json()
    assert schema["info"]["title"] == "KnowTwin API"
    assert "/health" in schema["paths"]


def test_inexistent_endpoint_returns_404():
    assert client_prod.get("/foo/bar/baz").status_code == 404


def test_post_health_method_not_allowed():
    assert client_prod.post("/health").status_code == 405


def test_schema_version_matches_db():
    import asyncio
    import asyncpg

    async def _check():
        try:
            conn = await asyncpg.connect(DATABASE_URL)
        except Exception:
            pytest.skip("postgres not available")
        try:
            row = await conn.fetchrow(
                "SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1"
            )
        finally:
            await conn.close()
        assert row is not None, "schema_version table is empty"
        assert row["version"] == SCHEMA_VERSION

    asyncio.run(_check())
