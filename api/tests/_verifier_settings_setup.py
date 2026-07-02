"""Verifier temp: create test keys for settings checks."""
import asyncio
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncpg
from auth import generate_api_key

DATABASE_URL = os.environ["DATABASE_URL"]

async def main():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Super key
        k, h = generate_api_key()
        await conn.execute(
            "INSERT INTO api_keys (key_hash, name, user_id, active) VALUES ($1, $2, 1, true)",
            h, "verifier-settings-super",
        )
        print(f"SUPER={k}")

        # Employee user + key
        uid = await conn.fetchval(
            "INSERT INTO users (name) VALUES ($1) RETURNING id", "settings_employee"
        )
        await conn.execute(
            "INSERT INTO project_members (project_id, user_id, role) VALUES (1, $1, $2)",
            uid, "employee",
        )
        k2, h2 = generate_api_key()
        await conn.execute(
            "INSERT INTO api_keys (key_hash, name, user_id, active) VALUES ($1, $2, $3, true)",
            h2, "verifier-emp-key", uid,
        )
        print(f"EMPLOYEE={k2}")
        print(f"EMP_UID={uid}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
