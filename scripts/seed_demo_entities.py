"""Seed Juan Garcia / Nova Consulting demo entities.

Populates: entity_dictionary, nodes, entity_expected_claims.
Idempotent (ON CONFLICT DO NOTHING). Run:
  docker exec knowtwin-api python scripts/seed_demo_entities.py
  # or from host:
  python scripts/seed_demo_entities.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import asyncpg

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://knowtwin:knowtwin_test_pass@localhost:5436/knowtwin",
)

DEMO_PROJECT_ID = 1

# 13 named entities from Brief §demo + pad to 60 total.
# Format: (name, entity_type)
DEMO_ENTITIES = [
    # --- Brief §demo 13 named ---
    ("Juan Garcia", "persona_interna"),
    ("Banco Norte", "cliente_cuenta"),
    ("RetailCo", "cliente_cuenta"),
    ("Elena Ros", "persona_interna"),
    ("Carlos Ruiz", "persona_interna"),
    ("Maria Lopez", "persona_interna"),
    ("Andres Martin", "persona_interna"),
    ("CloudBase", "proveedor"),
    ("PostgreSQL Migration", "proyecto"),
    ("ETL Pipeline", "sistema_componente"),
    ("reconciliation_service", "sistema_componente"),
    ("Logistica Sur", "cliente_cuenta"),
    ("Roberto Vidal", "persona_externa"),
    # --- Pad: additional realistic offboarding entities ---
    ("Nova Consulting", "organizacion"),
    ("Plan Banco Norte", "fuente_sesion"),
    ("ADR PostgreSQL", "decision_tecnica"),
    ("Contrato CloudBase", "fuente_sesion"),
    ("Wiki ETL", "fuente_sesion"),
    ("Informe P1", "fuente_sesion"),
    ("Plan RetailCo", "fuente_sesion"),
    ("Organigrama equipo", "fuente_sesion"),
    ("Correo renovacion", "fuente_sesion"),
    ("API Gateway", "sistema_componente"),
    ("Redis Cache", "tecnologia"),
    ("Kafka", "tecnologia"),
    ("Docker Swarm", "tecnologia"),
    ("Jenkins CI", "sistema_componente"),
    ("Grafana Monitoring", "sistema_componente"),
    ("Data Warehouse", "sistema_componente"),
    ("SLA CloudBase 4h", "acuerdo_informal"),
    ("Viernes sin deploys", "acuerdo_informal"),
    ("Backup nocturno manual", "procedimiento_operativo"),
    ("Deploy canary", "procedimiento_operativo"),
    ("Escalado incidencias P1", "procedimiento_operativo"),
    ("Deuda migracion Oracle", "deuda_tecnica"),
    ("Deuda tests integracion", "deuda_tecnica"),
    ("Riesgo vendor lock-in CloudBase", "riesgo"),
    ("Riesgo perdida bus factor ETL", "riesgo"),
    ("Riesgo caducidad contrato Norte", "riesgo"),
    ("Comite arquitectura", "decision_tecnica"),
    ("Decision microservicios", "decision_tecnica"),
    ("Decision monorepo", "decision_tecnica"),
    ("Pedro Sanchez", "persona_interna"),
    ("Ana Torres", "persona_interna"),
    ("Luis Fernandez", "persona_interna"),
    ("Laura Gomez", "persona_interna"),
    ("Fernando Diaz", "persona_interna"),
    ("Patricia Navarro", "persona_externa"),
    ("Sergio Blanco", "persona_externa"),
    ("Isabel Moreno", "persona_interna"),
    ("Consultora Ágil SL", "proveedor"),
    ("AWS", "proveedor"),
    ("Proyecto Fénix", "proyecto"),
    ("Proyecto Migración Cloud", "proyecto"),
    ("Proyecto Compliance GDPR", "proyecto"),
    ("Renovación Banco Norte", "proyecto"),
    ("Modulo facturación", "sistema_componente"),
    ("Servicio notificaciones", "sistema_componente"),
    ("Dashboard Financiero", "sistema_componente"),
    ("Sistema Facturacion", "sistema_componente"),
    ("Monitoring Stack", "sistema_componente"),
    ("CI/CD Pipeline", "sistema_componente"),
    ("Cloud Migration", "proyecto"),
    ("API Modernization", "proyecto"),
    ("Compliance Audit", "proyecto"),
    ("Incident Response", "procedimiento_operativo"),
    ("Data Reconciliation", "procedimiento_operativo"),
    ("Monthly Reporting", "procedimiento_operativo"),
    ("Deployment Process", "procedimiento_operativo"),
    ("Runbook ETL", "fuente_sesion"),
    ("Wiki Arquitectura", "fuente_sesion"),
    ("Documentacion API", "fuente_sesion"),
    ("Playbook Incidencias", "fuente_sesion"),
    ("Protocolo onboarding técnico", "procedimiento_operativo"),
    ("Runbook incidencias nocturnas", "procedimiento_operativo"),
    ("Acuerdo rotación guardia", "acuerdo_informal"),
]

# expected_count by entity_type (Plan P1.7)
_EXPECTED_COUNT = {
    "cliente_cuenta": 12,
    "sistema_componente": 8,
    "proyecto": 10,
}
_DEFAULT_EXPECTED_COUNT = 5

# expected_criticality overrides (Plan P1.7)
_CRITICALITY_OVERRIDES = {
    "Juan Garcia": 1.0,
    "Banco Norte": 0.9,
    "ETL Pipeline": 0.9,
    "CloudBase": 0.8,
    "Dashboard Financiero": 0.8,
    "Data Warehouse": 0.8,
    "RetailCo": 0.7,
    "Data Reconciliation": 0.9,
    "Incident Response": 0.8,
}
_OLD_CLOSED_NAMES = {
    "Deuda migracion Oracle",
    "Proyecto Fénix",
}
_DEFAULT_CRITICALITY = 0.5


def _expected_count(entity_type: str) -> int:
    return _EXPECTED_COUNT.get(entity_type, _DEFAULT_EXPECTED_COUNT)


def _expected_criticality(name: str) -> float:
    if name in _CRITICALITY_OVERRIDES:
        return _CRITICALITY_OVERRIDES[name]
    if name in _OLD_CLOSED_NAMES:
        return 0.2
    return _DEFAULT_CRITICALITY


def _normalize(name: str) -> str:
    import unicodedata
    decomposed = unicodedata.normalize("NFKD", name)
    no_accents = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return no_accents.lower().strip()


async def main():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        async with conn.transaction():
            # Ensure demo project exists
            proj = await conn.fetchval("SELECT id FROM projects WHERE id = $1", DEMO_PROJECT_ID)
            if proj is None:
                ws = await conn.fetchval("SELECT id FROM workspaces LIMIT 1")
                if ws is None:
                    org_id = await conn.fetchval(
                        "INSERT INTO organizations (name) VALUES ('Nova Consulting') "
                        "ON CONFLICT DO NOTHING RETURNING id"
                    )
                    if org_id is None:
                        org_id = await conn.fetchval("SELECT id FROM organizations LIMIT 1")
                    ws = await conn.fetchval(
                        "INSERT INTO workspaces (name, organization_id) VALUES ('Default', $1) "
                        "ON CONFLICT DO NOTHING RETURNING id",
                        org_id,
                    )
                    if ws is None:
                        ws = await conn.fetchval("SELECT id FROM workspaces LIMIT 1")
                await conn.execute(
                    "INSERT INTO projects (id, name, workspace_id) VALUES ($1, 'Juan Garcia Offboarding', $2) "
                    "ON CONFLICT (id) DO NOTHING",
                    DEMO_PROJECT_ID, ws,
                )

            inserted_dict = 0
            inserted_nodes = 0
            inserted_expected = 0

            for name, entity_type in DEMO_ENTITIES:
                name_norm = _normalize(name)

                # entity_dictionary
                result = await conn.execute(
                    "INSERT INTO entity_dictionary (name, name_normalized, entity_type) "
                    "VALUES ($1, $2, $3) ON CONFLICT (name_normalized) DO NOTHING",
                    name, name_norm, entity_type,
                )
                if "INSERT 0 1" in result:
                    inserted_dict += 1

                # nodes (for entity_coverage JOIN)
                result = await conn.execute(
                    "INSERT INTO nodes (name, type, status) "
                    "VALUES ($1, $2, 'active') ON CONFLICT (name) DO NOTHING",
                    name, entity_type,
                )
                if "INSERT 0 1" in result:
                    inserted_nodes += 1

                # entity_expected_claims (coverage denominator)
                ec = _expected_count(entity_type)
                crit = _expected_criticality(name)
                result = await conn.execute(
                    "INSERT INTO entity_expected_claims "
                    "(project_id, entity_name, entity_type, expected_count, expected_criticality) "
                    "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (project_id, entity_name) DO NOTHING",
                    DEMO_PROJECT_ID, name, entity_type, ec, crit,
                )
                if "INSERT 0 1" in result:
                    inserted_expected += 1

        print(f"Seeded {inserted_dict} entity_dictionary, "
              f"{inserted_nodes} nodes, "
              f"{inserted_expected} entity_expected_claims "
              f"(total entities: {len(DEMO_ENTITIES)})")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
