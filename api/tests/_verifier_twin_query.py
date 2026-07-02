"""Verifier temp: test twin query for ETL."""
import asyncio
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncpg
from auth import generate_api_key
from fastapi.testclient import TestClient
from main import create_app

DATABASE_URL = os.environ["DATABASE_URL"]

async def main():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        kp, kh = generate_api_key()
        await conn.execute(
            "INSERT INTO api_keys (key_hash, name, user_id, active) VALUES ($1, 'demo_twin_test', 1, true)",
            kh,
        )

        app = create_app("development")
        with TestClient(app) as client:
            resp = client.post("/twin/query", json={
                "question": "who runs the ETL pipeline?",
                "project_id": 1,
            }, headers={"Authorization": f"Bearer {kp}"})
            print(f"STATUS: {resp.status_code}")
            data = resp.json()
            print(f"ANSWER: {data['answer'][:200]}")
            print(f"SOURCES: {len(data['sources'])}")
            for s in data['sources']:
                print(f"  - {s['subject_entity']}.{s['predicate']}: {s.get('evidence_text','')[:80]} [{s['dispute_state']}]")

        await conn.execute("DELETE FROM api_keys WHERE name = 'demo_twin_test'")
    finally:
        await conn.close()

asyncio.run(main())
