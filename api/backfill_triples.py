"""One-shot backfill: materialize triples from existing claims.

Run inside api/ with DATABASE_URL set:
    cd api && DATABASE_URL=$KT_DSN python backfill_triples.py
"""
import asyncio
import os
import sys

import asyncpg

sys.path.insert(0, os.path.dirname(__file__))
from graph import _ensure_node, _create_age_edge

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://knowtwin:knowtwin_test_pass@localhost:5436/knowtwin",
)


async def backfill():
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch(
        "SELECT id, subject_entity, predicate, object_value, object_entity "
        "FROM claims WHERE corroboration_level != 'rejected' "
        "AND (object_value IS NOT NULL OR object_entity IS NOT NULL)"
    )
    count = 0
    for r in rows:
        subj_id = await _ensure_node(conn, r["subject_entity"])
        obj_name = r["object_entity"] or r["object_value"]
        if obj_name:
            obj_id = await _ensure_node(conn, obj_name)
            t_row = await conn.fetchrow(
                "INSERT INTO triples (subject_id, predicate, object_id, claim_id) "
                "VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING RETURNING id",
                subj_id, r["predicate"], obj_id, r["id"],
            )
            if t_row is not None:
                await _create_age_edge(conn, subj_id, r["predicate"], obj_id)
            count += 1
    print(f"Backfilled {count} triples from {len(rows)} claims")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(backfill())
