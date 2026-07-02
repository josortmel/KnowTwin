"""KnowTwin — Seed predicate vocabulary.

Inserts 10 offboarding + 10 core + 25 domain predicates (45 total) into predicates_canonical.
Optionally embeds each via Jina v4 (skips gracefully if tei is down).

Usage:
  docker exec knowtwin-api python /app/sql/seed_predicates.py
  # or from host with port-forwarded DB:
  DATABASE_URL=postgresql://knowtwin:...@localhost:5436/knowtwin python scripts/seed_predicates.py
"""
import asyncio
import asyncpg
import httpx
import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://knowtwin:knowtwin_test_pass@localhost:5436/knowtwin",
)
EMBEDDINGS_URL = os.environ.get("EMBEDDINGS_URL", "http://knowtwin-tei:8090")

# (name, cluster, ontology_layer, domain, description, symmetric, inverse_of, transitive, domain_types, range_types, authority_agents)
PREDICATES = [
    # === OFFBOARDING (10) — cluster='offboarding', ontology_layer='domain', domain='offboarding' ===
    ("responsable_de", "offboarding", "domain", "offboarding",
     "primary owner/responsible for a process, system, or area",
     False, None, False, ["persona"], ["proceso", "sistema", "area"], []),
    ("unico_conocedor_de", "offboarding", "domain", "offboarding",
     "sole knower — bus factor 1",
     False, None, False, ["persona"], ["proceso", "sistema", "concepto"], []),
    ("contacto_clave_de", "offboarding", "domain", "offboarding",
     "key external contact for vendor, client, or partner",
     False, None, False, ["persona"], ["organizacion", "persona"], []),
    ("aprobador_de", "offboarding", "domain", "offboarding",
     "approval authority in a workflow or process",
     False, None, False, ["persona"], ["proceso"], []),
    ("escalacion_para", "offboarding", "domain", "offboarding",
     "escalation point for incidents in an area",
     False, None, False, ["persona"], ["sistema", "proceso", "area"], []),
    ("sucede_a", "offboarding", "domain", "offboarding",
     "succession — who takes over responsibilities",
     False, "sucedido_por", False, ["persona"], ["persona"], []),
    ("sucedido_por", "offboarding", "domain", "offboarding",
     "inverse of sucede_a — designated successor",
     False, "sucede_a", False, ["persona"], ["persona"], []),
    ("credencial_para", "offboarding", "domain", "offboarding",
     "holds credentials or access for a system",
     False, None, False, ["persona"], ["sistema", "tecnologia"], []),
    ("procedimiento_no_documentado", "offboarding", "domain", "offboarding",
     "knows an undocumented procedure or workaround",
     False, None, False, ["persona"], ["proceso", "sistema"], []),
    ("riesgo_operacional_de", "offboarding", "domain", "offboarding",
     "operational risk if person is absent from area",
     False, None, False, ["persona"], ["area", "proceso", "sistema"], []),

    # === REUSED CORE (10) — from EcoDB vocabulary, ontology_layer='core' ===
    ("ensena_a", "conocimiento", "core", None,
     "knowledge transfer from one person to another",
     False, "aprende_de", False, ["persona"], ["persona"], []),
    ("aprende_de", "conocimiento", "core", None,
     "inverse of ensena_a",
     False, "ensena_a", False, ["persona"], ["persona"], []),
    ("sabe", "conocimiento", "core", None,
     "objective knowledge about a topic",
     False, None, False, ["persona"], [], []),
    ("afirma", "conocimiento", "core", None,
     "explicit declaration or assertion",
     False, None, False, ["persona"], [], []),
    ("verifica", "conocimiento", "core", None,
     "confirms or validates a claim",
     False, None, False, ["persona"], [], []),
    ("contradice", "conocimiento", "core", None,
     "semantic conflict between claims",
     True, None, False, [], [], []),
    ("depende_de", "arquitectura", "core", None,
     "functional dependency — does not work without",
     False, None, True, ["sistema", "proceso", "tecnologia"], ["sistema", "proceso", "tecnologia"], []),
    ("pertenece_a", "composicion", "core", None,
     "membership in a group or organization",
     False, None, False, ["persona"], ["organizacion", "proyecto"], []),
    ("parte_de", "composicion", "core", None,
     "component of a system or process",
     False, None, True, [], [], []),
    ("miembro_de", "composicion", "core", None,
     "formal membership",
     False, None, False, ["persona"], ["organizacion", "proyecto"], []),

    # === OPERACIONES (7) ===
    ("gestiona", "operaciones", "domain", None, "manages a process, system, or resource",
     False, None, False, [], [], []),
    ("mantiene", "operaciones", "domain", None, "maintains a system or process",
     False, None, False, [], [], []),
    ("monitoriza", "operaciones", "domain", None, "monitors a system or metric",
     False, None, False, [], [], []),
    ("opera", "operaciones", "domain", None, "operates a system or infrastructure",
     False, None, False, [], [], []),
    ("escala_a", "operaciones", "domain", None, "escalation path to person or team",
     False, None, False, [], [], []),
    ("domina", "operaciones", "domain", None, "has deep expertise in a topic",
     False, None, False, [], [], []),
    ("capacidad", "operaciones", "domain", None, "capacity or throughput of a system",
     False, None, False, [], [], []),

    # === RELACIONES (5) ===
    ("coordina_con", "relaciones", "domain", None, "coordinates with person or team",
     False, None, False, [], [], []),
    ("negocia_con", "relaciones", "domain", None, "negotiates with external party",
     False, None, False, [], [], []),
    ("reporta_a", "relaciones", "domain", None, "reports to person in hierarchy",
     False, None, False, [], [], []),
    ("sustituye_a", "relaciones", "domain", None, "substitutes for a person",
     False, None, False, [], [], []),
    ("contacto_clave", "relaciones", "domain", None, "key contact for a vendor or partner",
     False, None, False, [], [], []),

    # === DOCUMENTACION (3) ===
    ("documenta", "documentacion", "domain", None, "documents a process or decision",
     False, None, False, [], [], []),
    ("certifica", "documentacion", "domain", None, "certifies or validates formally",
     False, None, False, [], [], []),
    ("audita", "documentacion", "domain", None, "audits a system or process",
     False, None, False, [], [], []),

    # === TECNICO (5) ===
    ("implementa", "tecnico", "domain", None, "implements a system or feature",
     False, None, False, [], [], []),
    ("diseña", "tecnico", "domain", None, "designs architecture or solution",
     False, None, False, [], [], []),
    ("migra", "tecnico", "domain", None, "migrates data or systems",
     False, None, False, [], [], []),
    ("despliega", "tecnico", "domain", None, "deploys to production",
     False, None, False, [], [], []),
    ("decide_en", "tecnico", "domain", None, "technical decision authority in area",
     False, None, False, [], [], []),

    # === CONTRATOS/SLA (5) ===
    ("sla_hours", "contratos", "domain", None, "SLA response time commitment",
     False, None, False, [], [], []),
    ("riesgo_activo", "contratos", "domain", None, "active risk in contract or operation",
     False, None, False, [], [], []),
    ("acuerdo_informal", "contratos", "domain", None, "informal/verbal agreement",
     False, None, False, [], [], []),
    ("responsable_real", "contratos", "domain", None, "de facto responsible (vs formal)",
     False, None, False, [], [], []),
    ("workaround_conocido", "contratos", "domain", None, "known workaround for a limitation",
     False, None, False, [], [], []),
]


async def embed_predicate(client: httpx.AsyncClient, name: str) -> list[float] | None:
    try:
        r = await client.post(f"{EMBEDDINGS_URL}/embed/text", json={
            "texts": [name.replace("_", " ")],
            "task": "retrieval",
            "prompt_name": "passage",
            "truncate_dim": 512,
        }, timeout=30.0)
        if r.status_code == 200:
            return r.json()["embeddings"][0]
    except Exception as e:
        print(f"  WARNING: embed failed for {name}: {e}")
    return None


async def main():
    conn = await asyncpg.connect(DATABASE_URL)
    print(f"Seeding {len(PREDICATES)} predicates into KnowTwin...")

    async with conn.transaction():
        inserted = 0
        for p in PREDICATES:
            name, cluster, layer, domain, desc, sym, inv, trans, dt, rt, auth = p
            try:
                await conn.execute("""
                    INSERT INTO predicates_canonical
                    (name, cluster, ontology_layer, domain, description,
                     "symmetric", inverse_of, transitive,
                     domain_types, range_types, authority_agents, state)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'approved')
                    ON CONFLICT (name) DO NOTHING
                """, name, cluster, layer, domain, desc, sym, inv, trans, dt, rt, auth)
                inserted += 1
            except Exception as e:
                print(f"  ERROR inserting {name}: {e}")
        print(f"Inserted: {inserted}/{len(PREDICATES)}")

    print("\nEmbedding predicates with Jina v4 (skips if tei unavailable)...")
    async with httpx.AsyncClient() as client:
        embedded = 0
        for p in PREDICATES:
            name = p[0]
            vec = await embed_predicate(client, name)
            if vec:
                await conn.execute("""
                    UPDATE predicates_canonical
                    SET embedding = $1::vector, embedding_model = 'jina-v4', embedding_updated = now()
                    WHERE name = $2
                """, str(vec), name)
                embedded += 1
        print(f"Embedded: {embedded}/{len(PREDICATES)}")
        if embedded == 0:
            print("  (tei not running — predicates seeded without embeddings, will embed at P1.3)")

    total = await conn.fetchval("SELECT count(*) FROM predicates_canonical WHERE state = 'approved'")
    offboarding = await conn.fetchval("SELECT count(*) FROM predicates_canonical WHERE domain = 'offboarding'")
    print(f"\nFinal: {total} approved, {offboarding} offboarding")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
