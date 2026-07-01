# EXECUTOR_REPORT — P1.7: Entity dictionary + expected-claims seeding

**STATUS:** COMPLETE
**Task:** P1.7
**Executor:** executor-1
**Date:** 2026-07-01

## Files touched
1. `api/entity_normalization.py` — ALLOWED_ENTITY_TYPES expanded 12→18
2. `scripts/seed_demo_entities.py` — NEW, seeds 58 demo entities
3. `sql/init.sql` — trust_hint added (P1.8, already committed)

## Actions

### entity_normalization.py
- Replaced 12-type EcoDB allowlist with 18-type KnowTwin allowlist
- 13 offboarding domain types (Spec §2.6): persona_interna, persona_externa, cliente_cuenta, proveedor, proyecto, sistema_componente, tecnologia, decision_tecnica, riesgo, deuda_tecnica, acuerdo_informal, procedimiento_operativo, fuente_sesion
- 6 GLiNER generic: persona, organizacion, lugar, producto, agente_ia (+ proyecto overlap)
- Removed: concepto, evento, artefacto, modelo_ia, metodologia (EcoDB-specific, not in offboarding domain)

### seed_demo_entities.py
- 58 entities (13 named from Brief §demo + 45 realistic pad)
- Entity types: persona_interna(8), cliente_cuenta(3), proveedor(3), proyecto(5), sistema_componente(8), tecnologia(3), decision_tecnica(3), riesgo(3), deuda_tecnica(2), acuerdo_informal(3), procedimiento_operativo(5), fuente_sesion(7), persona_externa(3), organizacion(1)
- Seeds into 3 tables atomically: entity_dictionary + nodes + entity_expected_claims
- expected_count by type: cliente_cuenta=12, sistema_componente=8, proyecto=10, else 5
- expected_criticality: Banco Norte=0.9, ETL Pipeline=0.9, CloudBase=0.8, RetailCo=0.7, old closed=0.2, else 0.5
- Idempotent (ON CONFLICT DO NOTHING)
- Auto-creates project/workspace/org if absent

### gliner_service.py
- No changes needed — DEFAULT_LABELS unchanged per plan, dictionary cache picks up new types automatically

## Tests — literal output

```
SELECT count(*) FROM entity_dictionary;
 dict_count = 64   (≥50 ✓)

SELECT count(*) FROM entity_expected_claims WHERE project_id = 1;
 expected_claims_count = 58   (== entity count ✓)

SELECT count(*) FROM entity_coverage WHERE coverage_state = 'unknown';
 coverage_unknown = 58   (== entity count ✓)

SELECT count(*) FROM entity_expected_claims ec
LEFT JOIN nodes n ON n.name = ec.entity_name WHERE n.id IS NULL;
 orphans = 0   (✓)

ALLOWED_ENTITY_TYPES has 18 types
'cliente_cuenta' in ALLOWED_ENTITY_TYPES → True   (✓)
```

## Post-conditions
- 18-type allowlist reflects offboarding domain ✓
- ≥50 entities seeded (58) ✓
- Every entity has nodes row + entity_expected_claims row (0 orphans) ✓
- entity_coverage returns all entities with state='unknown', pct=0 pre-Curator ✓
- GLiNER DEFAULT_LABELS unchanged ✓
