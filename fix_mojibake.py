import asyncio, asyncpg, os

async def fix():
    conn = await asyncpg.connect(os.environ.get(
        "DATABASE_URL",
        "postgresql://knowtwin:knowtwin_test_pass@knowtwin-db:5432/knowtwin"
    ))
    rows = await conn.fetch(
        "SELECT id, evidence_text FROM claims "
        "WHERE source_type = 'document' AND evidence_text LIKE '%Ã%'"
    )
    fixed = 0
    for r in rows:
        try:
            corrected = r["evidence_text"].encode("latin-1").decode("utf-8")
            await conn.execute(
                "UPDATE claims SET evidence_text = $1 WHERE id = $2",
                corrected, r["id"],
            )
            fixed += 1
            print(f"  {r['id']}: {r['evidence_text'][:40]} → {corrected[:40]}")
        except (UnicodeDecodeError, UnicodeEncodeError) as e:
            print(f"  SKIP {r['id']}: {e}")
    print(f"\nFixed {fixed}/{len(rows)} claims")
    await conn.close()

asyncio.run(fix())
