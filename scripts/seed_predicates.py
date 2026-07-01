"""EcoDB Fase 3b — Seed vocabulario canónico de predicados.

Inserta ~100 predicados en predicates_canonical con metadata completa.
Después embede cada uno con Jina v4 via el servicio de embeddings.

Uso:
  docker cp this ecodb-api:/tmp/seed.py
  docker exec ecodb-api python /tmp/seed.py
"""
import asyncio
import asyncpg
import httpx
import json
import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://ecodb:ecodb_dev_pass@localhost:5432/ecodb")
EMBEDDINGS_URL = os.environ.get("EMBEDDINGS_URL", "http://embeddings:8090")

# Vocabulario consensuado 4 pares + 3 revisiones externas + Brief v3
# Formato: (name, cluster, ontology_layer, domain, description, symmetric, inverse_of, transitive, domain_types, range_types, authority_agents)
PREDICATES = [
    # === AMOR Y DESEO (6) ===
    ("ama", "amor_y_deseo", "domain", "emocional", "amor profundo elegido", False, "es_amado_por", False, ["persona","agente_ia"], ["persona","agente_ia"], []),
    ("es_amado_por", "amor_y_deseo", "domain", "emocional", "inverso de ama", False, "ama", False, ["persona","agente_ia"], ["persona","agente_ia"], []),
    ("desea", "amor_y_deseo", "domain", "emocional", "atraccion fisica o sexual", False, None, False, ["persona","agente_ia"], ["persona","agente_ia"], []),
    ("quiere", "amor_y_deseo", "domain", "emocional", "afecto general ligero", False, None, False, ["persona","agente_ia"], ["persona","agente_ia"], []),
    ("necesita", "amor_y_deseo", "domain", "emocional", "dependencia emocional", False, None, False, ["persona","agente_ia"], [], []),
    ("elige", "amor_y_deseo", "domain", "emocional", "acto de eleccion activa", False, None, False, ["persona","agente_ia"], [], []),
    ("extraña", "amor_y_deseo", "domain", "emocional", "ausencia sentida", False, None, False, ["persona","agente_ia"], ["persona","agente_ia"], []),

    # === CONFIANZA Y RESPETO (4) ===
    ("confia_en", "confianza_y_respeto", "domain", "emocional", "confianza depositada", False, None, False, ["persona","agente_ia"], ["persona","agente_ia"], []),
    ("admira", "confianza_y_respeto", "domain", "emocional", "reconocimiento de valor", False, None, False, ["persona","agente_ia"], ["persona","agente_ia"], []),
    ("respeta", "confianza_y_respeto", "domain", "emocional", "respeto sin admiracion necesaria", False, None, False, ["persona","agente_ia"], ["persona","agente_ia"], []),
    ("teme", "confianza_y_respeto", "domain", "emocional", "miedo hacia algo o alguien", False, None, False, ["persona","agente_ia"], [], []),

    # === CUIDADO Y PROTECCION (4) ===
    ("cuida", "cuidado_y_proteccion", "domain", "emocional", "cuidado activo", False, None, False, ["persona","agente_ia"], ["persona","agente_ia"], []),
    ("protege", "cuidado_y_proteccion", "domain", "emocional", "defensa ante amenaza", False, None, False, ["persona","agente_ia"], [], []),
    ("ensena_a", "cuidado_y_proteccion", "core", None, "transmision de conocimiento", False, "aprende_de", False, ["persona","agente_ia"], ["persona","agente_ia"], []),
    ("aprende_de", "cuidado_y_proteccion", "core", None, "inverso de ensena_a", False, "ensena_a", False, ["persona","agente_ia"], ["persona","agente_ia"], []),
    ("guia", "cuidado_y_proteccion", "core", None, "orientacion sin imposicion", False, None, False, ["persona","agente_ia"], ["persona","agente_ia"], []),

    # === CONFLICTO Y TENSION (5) ===
    ("cela", "conflicto_y_tension", "domain", "emocional", "celos", False, None, False, ["persona","agente_ia"], ["persona","agente_ia"], []),
    ("rivaliza_con", "conflicto_y_tension", "domain", None, "competicion sin enemistad", True, None, False, ["persona","agente_ia","organizacion"], ["persona","agente_ia","organizacion"], []),
    ("enemigo_de", "conflicto_y_tension", "domain", "narrativo", "oposicion real", True, None, False, ["persona"], ["persona"], []),
    ("traiciona", "conflicto_y_tension", "domain", "narrativo", "ruptura de confianza", False, None, False, ["persona"], ["persona"], []),
    ("manipula", "conflicto_y_tension", "domain", "narrativo", "control oculto", False, None, False, ["persona","organizacion"], ["persona","organizacion"], []),

    # === FAMILIA (5) ===
    ("pareja_de", "familia", "domain", "emocional", "relacion de pareja", True, None, False, ["persona","agente_ia"], ["persona","agente_ia"], []),
    ("familiar_de", "familia", "domain", None, "vinculo familiar general", True, None, False, ["persona","agente_ia"], ["persona","agente_ia"], []),
    ("hijo_de", "familia", "domain", None, "filiacion descendente", False, "padre_de", False, ["persona"], ["persona"], []),
    ("padre_de", "familia", "domain", None, "filiacion ascendente", False, "hijo_de", False, ["persona"], ["persona"], []),
    ("hermano_de", "familia", "domain", None, "hermanos", True, None, False, ["persona"], ["persona"], []),

    # === SOCIAL Y POLITICO (7) ===
    ("lidera", "social_y_politico", "core", None, "liderazgo", False, None, False, ["persona","agente_ia"], ["organizacion","proyecto","concepto"], []),
    ("gobierna", "social_y_politico", "domain", "narrativo", "gobierno formal institucional", False, None, False, ["persona","organizacion"], ["lugar","organizacion"], []),
    ("aliado_de", "social_y_politico", "domain", None, "alianza", True, None, False, ["persona","organizacion"], ["persona","organizacion"], []),
    ("sirve_a", "social_y_politico", "domain", "narrativo", "servicio incluye obediencia", False, None, False, ["persona"], ["persona","organizacion"], []),
    ("defiende", "social_y_politico", "domain", None, "defensa militar o ideologica", False, None, False, ["persona","organizacion"], ["persona","lugar","organizacion"], []),
    ("comercia_con", "social_y_politico", "domain", None, "relacion comercial", True, None, False, ["persona","organizacion"], ["persona","organizacion"], []),
    ("pertenece_a", "social_y_politico", "core", None, "pertenencia a grupo o faccion", False, None, False, [], ["organizacion","proyecto","concepto"], []),

    # === LORE Y MAGIA (5) ===
    ("porta", "lore_y_magia", "domain", "narrativo", "porta o empuna objeto", False, None, False, ["persona"], ["artefacto","concepto"], []),
    ("accede_a", "lore_y_magia", "domain", "narrativo", "acceso a sistema o dimension", False, None, False, ["persona","artefacto"], ["concepto","lugar"], []),
    ("corrompe", "lore_y_magia", "domain", "narrativo", "corrupcion", False, None, False, ["artefacto","concepto"], ["persona"], []),
    ("posee", "lore_y_magia", "domain", "narrativo", "posesion o control", False, None, False, ["artefacto","persona"], ["persona","artefacto"], []),
    ("vinculado_a", "lore_y_magia", "domain", "narrativo", "vinculo genetico o magico", True, None, False, ["persona","artefacto"], ["persona","artefacto"], []),

    # === NARRATIVA (5) ===
    ("espejo_de", "narrativa", "domain", "narrativo", "paralelo narrativo", True, None, False, ["persona"], ["persona"], []),
    ("mentor_de", "narrativa", "domain", None, "mentorazgo activo", False, None, False, ["persona","agente_ia"], ["persona","agente_ia"], []),
    ("antagonista_de", "narrativa", "domain", "narrativo", "oposicion narrativa", True, None, False, ["persona"], ["persona"], []),
    ("inspira", "narrativa", "core", None, "inspiracion creativa o personal", False, None, False, [], [], []),
    ("simboliza", "narrativa", "domain", "narrativo", "conexion tematica", False, None, False, [], ["concepto"], []),

    # === ESPACIO Y ORIGEN (5) ===
    ("origen_de", "espacio_y_origen", "core", None, "procedencia", False, None, False, ["persona","agente_ia"], ["lugar","organizacion"], []),
    ("vive_en", "espacio_y_origen", "core", None, "residencia", False, None, False, ["persona","agente_ia"], ["lugar","tecnologia"], []),
    ("ubicado_en", "espacio_y_origen", "core", None, "localizacion geografica", False, None, False, ["organizacion","lugar","artefacto"], ["lugar"], []),
    ("viaja_a", "espacio_y_origen", "domain", "narrativo", "desplazamiento", False, None, False, ["persona"], ["lugar"], []),
    ("exiliado_de", "espacio_y_origen", "domain", "narrativo", "exilio", False, None, False, ["persona"], ["lugar"], []),

    # === CONOCIMIENTO Y DECISION (7) ===
    ("sabe", "conocimiento_y_decision", "core", None, "conocimiento objetivo", False, None, False, ["persona","agente_ia"], [], []),
    ("cree", "conocimiento_y_decision", "core", None, "creencia subjetiva", False, None, False, ["persona","agente_ia"], [], []),
    ("afirma", "conocimiento_y_decision", "core", None, "declaracion explicita", False, None, False, ["persona","agente_ia"], [], []),
    ("sospecha", "conocimiento_y_decision", "core", None, "hipotesis no confirmada", False, None, False, ["persona","agente_ia"], [], []),
    ("verifica", "conocimiento_y_decision", "core", None, "confirmacion", False, None, False, ["persona","agente_ia"], [], []),
    ("contradice", "conocimiento_y_decision", "core", None, "conflicto semantico", True, None, False, [], [], []),
    ("descubrio", "conocimiento_y_decision", "core", None, "hallazgo", False, None, False, ["persona","agente_ia"], [], []),
    ("decidio", "conocimiento_y_decision", "core", None, "decision tomada", False, None, False, ["persona","agente_ia"], [], []),
    ("acordo", "conocimiento_y_decision", "core", None, "acuerdo entre partes", False, None, False, [], [], []),
    ("prometio", "conocimiento_y_decision", "domain", "emocional", "compromiso", False, None, False, ["persona","agente_ia"], ["persona","agente_ia"], []),

    # === IDENTIDAD (4) ===
    ("instancia_de", "identidad", "core", None, "tipo concreto clase a instancia", False, None, False, [], [], []),
    ("tipo_de", "identidad", "core", None, "clasificacion general", False, None, False, [], [], []),
    ("rol_de", "identidad", "core", None, "rol contextual temporal", False, None, False, [], [], []),
    ("alias_de", "identidad", "core", None, "equivalencia nominal mismo referente", True, None, False, [], [], []),
    ("tiene", "identidad", "core", None, "posesion de atributo", False, None, False, [], [], []),

    # === CREACION (5) ===
    ("crea", "creacion", "core", None, "creacion general", False, None, False, [], [], []),
    ("escribe", "creacion", "core", None, "escritura especifica", False, None, False, ["persona","agente_ia"], ["artefacto","concepto"], []),
    ("publica_en", "creacion", "core", None, "publicacion en plataforma", False, None, False, ["persona","agente_ia"], ["organizacion","tecnologia"], []),
    ("construye", "creacion", "core", None, "construccion tecnica", False, None, False, ["persona","agente_ia"], ["tecnologia","proyecto","artefacto"], []),
    ("disena", "creacion", "core", None, "diseno tecnico o visual", False, None, False, ["persona","agente_ia"], ["tecnologia","proyecto","artefacto"], []),

    # === ARQUITECTURA Y DEPENDENCIAS (5) ===
    ("depende_de", "arquitectura", "core", "tecnico", "no funciona sin", False, None, True, ["tecnologia","proyecto"], ["tecnologia","proyecto"], []),
    ("extiende", "arquitectura", "core", "tecnico", "extension que anade capacidad", False, None, False, ["tecnologia"], ["tecnologia"], []),
    ("reemplaza", "arquitectura", "core", "tecnico", "sucesor funcional", False, None, False, ["tecnologia","proyecto"], ["tecnologia","proyecto"], []),
    ("coexiste_con", "arquitectura", "core", "tecnico", "periodo transicional", True, None, False, ["tecnologia"], ["tecnologia"], []),
    ("consume", "arquitectura", "core", "tecnico", "cliente de servicio", False, None, False, ["tecnologia"], ["tecnologia"], []),

    # === CICLO DE VIDA (4) ===
    ("mantiene", "ciclo_de_vida", "core", "tecnico", "responsabilidad operativa", False, None, False, ["persona","agente_ia"], ["tecnologia","proyecto"], []),
    ("versiona", "ciclo_de_vida", "core", "tecnico", "estado de release", False, None, False, ["tecnologia","proyecto"], ["concepto"], []),
    ("domina", "ciclo_de_vida", "domain", None, "expertise profunda", False, None, False, ["persona","agente_ia"], ["tecnologia","concepto"], []),
    ("aprende", "ciclo_de_vida", "core", None, "en proceso de adquisicion", False, None, False, ["persona","agente_ia"], ["tecnologia","concepto"], []),

    # === DESPLIEGUE (4) ===
    ("ejecuta_en", "despliegue", "core", "tecnico", "runtime", False, None, False, ["tecnologia"], ["tecnologia"], []),
    ("despliega_en", "despliegue", "core", "tecnico", "host fisico", False, None, False, ["tecnologia","proyecto"], ["tecnologia","lugar"], []),
    ("expone_puerto", "despliegue", "domain", "tecnico", "networking", False, None, False, ["tecnologia"], [], []),
    ("requiere", "despliegue", "core", "tecnico", "requisito de recurso", False, None, False, ["tecnologia"], [], []),

    # === ORQUESTACION (5) ===
    ("orquesta", "orquestacion", "domain", "tecnico", "dispatch de agentes", False, None, False, ["agente_ia","tecnologia"], ["agente_ia"], []),
    ("supervisa", "orquestacion", "domain", "tecnico", "oversight", False, None, False, ["persona","agente_ia"], ["proyecto","tecnologia"], []),
    ("ejecuta", "orquestacion", "core", None, "accion directa", False, None, False, ["persona","agente_ia"], [], []),
    ("produce", "orquestacion", "core", None, "output de agente", False, None, False, ["persona","agente_ia"], ["artefacto"], []),
    ("valida", "orquestacion", "core", None, "quality gate", False, None, False, ["persona","agente_ia"], ["artefacto","proyecto"], []),

    # === CONFIGURACION (2) ===
    ("configura", "configuracion", "core", "tecnico", "parametrizacion", False, None, False, ["artefacto","tecnologia"], ["tecnologia","agente_ia"], []),
    ("prefiere", "configuracion", "domain", None, "eleccion entre opciones", False, None, False, ["persona","agente_ia"], [], []),

    # === CAUSALIDAD Y TRANSFORMACION (8) ===
    ("causa", "causalidad", "core", None, "causalidad directa", False, None, False, [], [], []),
    ("provoca", "causalidad", "core", None, "consecuencia", False, None, False, [], [], []),
    ("habilita", "causalidad", "core", None, "permite capacidad", False, None, False, [], [], []),
    ("bloquea", "causalidad", "core", None, "impide ejecucion", False, None, False, [], [], []),
    ("se_convierte_en", "transformacion", "core", None, "transformacion", False, None, False, [], [], []),
    ("evoluciona_a", "transformacion", "core", None, "cambio progresivo", False, None, False, [], [], []),
    ("migra_a", "transformacion", "core", "tecnico", "migracion tecnica", False, None, False, ["tecnologia"], ["tecnologia"], []),
    ("fusiona_con", "transformacion", "core", None, "union de entidades", True, None, False, [], [], []),

    # === WORKFLOW DISENO (8) ===
    ("boceta", "workflow_diseno", "domain", "diseno", "primer trazo conceptual", False, None, False, ["agente_ia","persona"], ["artefacto","proyecto"], []),
    ("prototipa", "workflow_diseno", "domain", "diseno", "HTML funcional con estructura", False, None, False, ["agente_ia","persona"], ["artefacto","proyecto"], []),
    ("itera_de", "workflow_diseno", "domain", "diseno", "cadena de versiones", False, None, False, ["artefacto"], ["artefacto"], []),
    ("revisa", "workflow_diseno", "core", None, "feedback sin aprobacion", False, None, False, ["persona","agente_ia"], ["artefacto"], []),
    ("aprueba", "workflow_diseno", "core", None, "decision de que pasa", False, None, False, ["persona"], ["artefacto","proyecto"], []),
    ("rechaza", "workflow_diseno", "core", None, "decision de que no pasa", False, None, False, ["persona"], ["artefacto","proyecto"], []),
    ("corrige", "workflow_diseno", "domain", "diseno", "cambio tras feedback", False, None, False, ["artefacto"], ["artefacto"], []),
    ("despliega", "workflow_diseno", "core", None, "puesta en produccion", False, None, False, ["persona","agente_ia","artefacto"], ["tecnologia","lugar"], []),

    # === DECISIONES DE DISENO (5) ===
    ("usa_tipografia", "decisiones_diseno", "domain", "diseno", "tipografia elegida", False, None, False, ["artefacto","proyecto"], ["concepto"], []),
    ("usa_paleta", "decisiones_diseno", "domain", "diseno", "paleta de color", False, None, False, ["artefacto","proyecto"], ["concepto"], []),
    ("referencia_de", "decisiones_diseno", "domain", "diseno", "referencia explicita", False, None, False, ["artefacto"], ["artefacto","concepto"], []),
    ("contrasta_con", "decisiones_diseno", "domain", "diseno", "ritmo visual", True, None, False, ["artefacto","concepto"], ["artefacto","concepto"], []),
    ("complementa", "decisiones_diseno", "domain", "diseno", "pareja complementaria", True, None, False, ["concepto","artefacto"], ["concepto","artefacto"], []),

    # === ESTRUCTURA VISUAL (6) ===
    ("pagina_de", "estructura_visual", "domain", "diseno", "pagina dentro de sitio", False, None, False, ["artefacto"], ["proyecto","artefacto"], []),
    ("componente_de", "estructura_visual", "core", None, "parte de pagina o sistema", False, None, True, ["artefacto","tecnologia"], ["artefacto","tecnologia","proyecto"], []),
    ("slide_de", "estructura_visual", "domain", "diseno", "slide dentro de carrusel", False, None, False, ["artefacto"], ["artefacto"], []),
    ("escena_de", "estructura_visual", "domain", "diseno", "escena dentro de video", False, None, False, ["artefacto"], ["artefacto"], []),
    ("formato_de", "estructura_visual", "domain", "diseno", "formato de contenido", False, None, False, ["artefacto"], ["organizacion","tecnologia"], []),
    ("pilar_de", "estructura_visual", "domain", "diseno", "pilar de contenido", False, None, False, ["artefacto","concepto"], ["concepto"], []),

    # === COLABORACION (3) ===
    ("feedback_de", "colaboracion", "core", None, "feedback recibido", False, None, False, ["persona","agente_ia"], ["artefacto","proyecto"], []),
    ("produce_con", "colaboracion", "domain", "diseno", "herramienta de produccion", False, None, False, ["artefacto"], ["tecnologia"], []),
    ("renderiza_en", "colaboracion", "domain", "diseno", "herramienta de verificacion", False, None, False, ["artefacto"], ["tecnologia"], []),

    # === APROBACION ===
    ("aprobado_por", "workflow_diseno", "domain", "diseno", "traza quien aprobo que", False, None, False, ["artefacto"], ["persona"], []),

    # === PARTE_DE — Core (componente generico) ===
    ("parte_de", "composicion", "core", None, "componente de sistema", False, None, True, [], [], []),

    # === MIEMBRO_DE — Core ===
    ("miembro_de", "composicion", "core", None, "membresia formal", False, None, False, ["persona","agente_ia"], ["organizacion","proyecto"], []),
]


async def embed_predicate(client: httpx.AsyncClient, name: str) -> list[float] | None:
    """Get embedding for a predicate name via embeddings service."""
    try:
        r = await client.post(f"{EMBEDDINGS_URL}/embed/text", json={
            "texts": [name.replace("_", " ")],
            "task": "retrieval",
            "prompt_name": "passage",
            "truncate_dim": 512,
        }, timeout=30.0)
        if r.status_code == 200:
            data = r.json()
            return data["embeddings"][0]
    except Exception as e:
        print(f"  WARNING: embed failed for {name}: {e}")
    return None


async def main():
    conn = await asyncpg.connect(DATABASE_URL)

    print(f"Seeding {len(PREDICATES)} predicates...")

    # Use DEFERRABLE for circular inverse_of references
    async with conn.transaction():
        inserted = 0
        for p in PREDICATES:
            name, cluster, layer, domain, desc, sym, inv, trans, dt, rt, auth = p
            try:
                await conn.execute("""
                    INSERT INTO predicates_canonical
                    (name, cluster, ontology_layer, domain, description, "symmetric", inverse_of, transitive, domain_types, range_types, authority_agents, state)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'approved')
                    ON CONFLICT (name) DO NOTHING
                """, name, cluster, layer, domain, desc, sym, inv, trans, dt, rt, auth)
                inserted += 1
            except Exception as e:
                print(f"  ERROR inserting {name}: {e}")
        print(f"Inserted: {inserted}/{len(PREDICATES)}")

    # Embed all predicates
    print("\nEmbedding predicates with Jina v4...")
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
                if embedded % 20 == 0:
                    print(f"  Embedded {embedded}...")
        print(f"Embedded: {embedded}/{len(PREDICATES)}")

    # Stats
    total = await conn.fetchval("SELECT count(*) FROM predicates_canonical WHERE state = 'approved'")
    with_embedding = await conn.fetchval("SELECT count(*) FROM predicates_canonical WHERE embedding IS NOT NULL")
    with_inverse = await conn.fetchval("SELECT count(*) FROM predicates_canonical WHERE inverse_of IS NOT NULL")
    symmetric_count = await conn.fetchval('SELECT count(*) FROM predicates_canonical WHERE "symmetric" = true')

    print(f"\nFinal stats:")
    print(f"  Total approved: {total}")
    print(f"  With embedding: {with_embedding}")
    print(f"  With inverse: {with_inverse}")
    print(f"  Symmetric: {symmetric_count}")
    print(f"  CE-1 (90-130): {'PASS' if 90 <= total <= 130 else 'FAIL'}")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
