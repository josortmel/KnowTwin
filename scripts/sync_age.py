"""Sync AGE graph with SQL tables post-purge."""
import asyncio
import asyncpg
import json
import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://ecodb:ecodb_dev_pass@localhost:5432/ecodb")

async def main():
    conn = await asyncpg.connect(DATABASE_URL)

    # Stats before
    age_nodes = await conn.fetchval("SELECT * FROM cypher('knowtwin_graph', $$MATCH (n) RETURN count(n)$$) AS (c agtype)")
    age_edges = await conn.fetchval("SELECT * FROM cypher('knowtwin_graph', $$MATCH ()-[r]->() RETURN count(r)$$) AS (c agtype)")
    sql_nodes = await conn.fetchval("SELECT count(*) FROM nodes")
    sql_triples = await conn.fetchval("SELECT count(*) FROM triples")
    print(f"ANTES: AGE {age_nodes} nodos / {age_edges} edges, SQL {sql_nodes} nodos / {sql_triples} triples")

    # Delete all edges then all nodes in AGE
    print("Vaciando AGE...")
    await conn.execute("SELECT * FROM cypher('knowtwin_graph', $$MATCH ()-[r]->() DELETE r$$) AS (d agtype)")
    await conn.execute("SELECT * FROM cypher('knowtwin_graph', $$MATCH (n) DELETE n$$) AS (d agtype)")

    check = await conn.fetchval("SELECT * FROM cypher('knowtwin_graph', $$MATCH (n) RETURN count(n)$$) AS (c agtype)")
    print(f"AGE vaciado: {check} nodos")

    # Recreate nodes from SQL — include sql_id for _create_age_edge compatibility
    nodes = await conn.fetch("SELECT id, name FROM nodes")
    print(f"Recreando {len(nodes)} nodos con sql_id...")
    for r in nodes:
        params = json.dumps({"name": r["name"], "sql_id": r["id"]})
        await conn.execute(
            "SELECT * FROM cypher('knowtwin_graph', $$CREATE (:Entity {name: $name, sql_id: $sql_id})$$, $1::agtype) AS (d agtype)",
            params,
        )

    # Recreate edges from triples — use sql_id like _create_age_edge does
    triples = await conn.fetch(
        "SELECT t.subject_id, s.name AS sname, t.predicate, t.object_id, o.name AS oname "
        "FROM triples t JOIN nodes s ON s.id = t.subject_id JOIN nodes o ON o.id = t.object_id"
    )
    print(f"Recreando {len(triples)} edges...")
    skipped = 0
    for t in triples:
        params = json.dumps({"sid": t["subject_id"], "oid": t["object_id"], "pred": t["predicate"]})
        try:
            await conn.execute(
                "SELECT * FROM cypher('knowtwin_graph', "
                "$$MATCH (s:Entity {sql_id: $sid}), (t:Entity {sql_id: $oid}) "
                "CREATE (s)-[:RELATES_TO {predicate: $pred}]->(t)$$, "
                "$1::agtype) AS (d agtype)",
                params,
            )
        except Exception as e:
            skipped += 1
            if skipped <= 5:
                print(f"  SKIP: {t['sname']}->{t['oname']}: {e}")

    # Stats after
    age_nodes_after = await conn.fetchval("SELECT * FROM cypher('knowtwin_graph', $$MATCH (n) RETURN count(n)$$) AS (c agtype)")
    age_edges_after = await conn.fetchval("SELECT * FROM cypher('knowtwin_graph', $$MATCH ()-[r]->() RETURN count(r)$$) AS (c agtype)")

    print(f"\nDESPUES:")
    print(f"  AGE: {age_nodes_after} nodos / {age_edges_after} edges")
    print(f"  SQL: {sql_nodes} nodos / {sql_triples} triples")
    print(f"  Skipped edges: {skipped}")
    print(f"  Sync: {'OK' if age_nodes_after == sql_nodes else 'MISMATCH'}")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
