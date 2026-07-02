"""One-shot backfill: populate claim_document_links from existing claims."""
import asyncio
import os
import sys

import asyncpg

sys.path.insert(0, os.path.dirname(__file__))

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://knowtwin:knowtwin_test_pass@localhost:5436/knowtwin",
)


async def backfill():
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch(
        "SELECT c.id AS claim_id, dc.document_id "
        "FROM claims c "
        "JOIN document_chunks dc ON dc.id = c.source_id::uuid "
        "WHERE c.source_type = 'document' AND c.source_id IS NOT NULL"
    )
    count = 0
    for r in rows:
        await conn.execute(
            "INSERT INTO claim_document_links (claim_id, document_id) "
            "VALUES ($1, $2) ON CONFLICT DO NOTHING",
            r["claim_id"], r["document_id"],
        )
        count += 1
    total = await conn.fetchval("SELECT count(*) FROM claim_document_links")
    print(f"Linked {count} claims to documents, total in table: {total}")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(backfill())
