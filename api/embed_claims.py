"""Embed all unembedded eligible claims."""
import asyncio
import os
import sys

import asyncpg

sys.path.insert(0, os.path.dirname(__file__))
from embeddings_client import embed_text

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://knowtwin:knowtwin_test_pass@localhost:5436/knowtwin",
)


async def main():
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch(
        "SELECT id, evidence_text FROM claims "
        "WHERE embedding IS NULL "
        "AND corroboration_level IN ('single_source','corroborated','corroborated_by_employee','validated')"
    )
    ok = 0
    fail = 0
    for r in rows:
        try:
            vec = await embed_text(r["evidence_text"], prompt_name="passage")
            if vec:
                await conn.execute(
                    "UPDATE claims SET embedding = $1::vector, embedding_model = 'jina-v4' WHERE id = $2",
                    str(vec), r["id"],
                )
                ok += 1
        except Exception as e:
            fail += 1
            if fail <= 3:
                print(f"  WARN: {e}")
    print(f"Embedded {ok}/{len(rows)}, failed {fail}")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
