"""One-shot backfill: populate claim_entity_links from existing claims."""
import asyncio
import os
import sys

import asyncpg

sys.path.insert(0, os.path.dirname(__file__))
from graph import _ensure_node

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://knowtwin:knowtwin_test_pass@localhost:5436/knowtwin",
)


async def backfill():
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch(
        "SELECT id, subject_entity, object_entity, object_value FROM claims"
    )
    count = 0
    for r in rows:
        subj_id = await _ensure_node(conn, r["subject_entity"])
        await conn.execute(
            "INSERT INTO claim_entity_links (claim_id, entity_node_id) "
            "VALUES ($1, $2) ON CONFLICT DO NOTHING",
            r["id"], subj_id,
        )
        count += 1
        obj_name = r.get("object_entity") or r.get("object_value")
        if obj_name:
            obj_id = await _ensure_node(conn, obj_name)
            await conn.execute(
                "INSERT INTO claim_entity_links (claim_id, entity_node_id) "
                "VALUES ($1, $2) ON CONFLICT DO NOTHING",
                r["id"], obj_id,
            )
            count += 1
    total = await conn.fetchval("SELECT count(*) FROM claim_entity_links")
    print(f"Created {count} links, total in table: {total}")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(backfill())
