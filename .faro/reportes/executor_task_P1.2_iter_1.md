# EXECUTOR_REPORT — P1.2 Schema Adaptation (iter-1)

**Task**: P1.2 — Schema adaptation (init.sql)
**Executor**: executor-1
**Date**: 2026-07-01
**Status**: COMPLETE — all tests pass

## What was done

### A. Consolidated init.sql (§0–§24, ~870 lines)

Single-file consolidated schema replacing the P1.1 minimal bootstrap. No migration runner.

**AS-IS core (~33 tables)** lifted from:
- `EcoDB/sql/init.sql` (v5.0.0 baseline)
- `migrate_5.0.1_to_5.1.0.sql` (multi-tenant: users.organization_id, api_keys rotation, teams.organization_id, audit_log.organization_id, org propagation triggers, team cross-org constraints)
- `migrate_08_agents.sql` (cognition_class on agents)
- `migrate_5.2.0_to_5.3.0_memory_agent.sql` (cell_prompt_templates, cell_task_configs, llm_provider_keys, agents display_name/description)
- `migrate_3_0h_multimodal.sql` (nodes.name_canonical GENERATED column)
- `migrate_5.1.0_to_5.1.1.sql` (graph_clusters for Louvain)

All folded inline — no ALTER chains, columns consolidated into CREATE TABLE.

**NEW/adapted tables**:
- `claims` (Spec §2.2 — 5 typed axes, embedding vector(512) nullable, all 12 indexes including HNSW + partial idx_claims_disputed_by)
- `claim_entity_links` / `claim_document_links` (renamed from memory_*_links, memory_id→claim_id)
- `interview_sessions` (§2.3), `verified_documents` (§2.4), `entity_expected_claims` (§2.5)
- `verifier_reports`, `deletion_requests` (§2.5.05)
- `predicates_canonical` (RICH, ~20 cols from governance.en.md §4)
- `predicate_aliases` (PK(alias, domain) — **domain NOT NULL DEFAULT ''** fixing the governance §4 nullable-PK bug)
- `entity_coverage` VIEW (§2.5.2, with `::numeric` cast for `ROUND()`)
- `project_members.role` TEXT CHECK (admin/curator/employee/consumer)
- `triples.claim_id` UUID REFERENCES claims(id) ON DELETE CASCADE + partial index
- AGE sync triggers referencing `knowtwin_graph` (NOT ecodb_graph)

**DROPPED** (never created):
- memories, memory_type enum, content_modality enum, memory_type_config
- agent_identity, memory_clusters, memory_embeddings, predicate_embeddings
- check_visibility() function, ecodb_cell role + RLS + GRANTs

### B. seed_predicates.py

20 predicates: 10 offboarding (cluster='offboarding', ontology_layer='domain', domain='offboarding') + 10 reused core. Embeddings skipped (tei not running — P1.3).

### C. Carried debt fixed

| ID | Fix |
|----|-----|
| BC3 | Stripped GET /stats/metacognition + 7 Pydantic models from stats.py (147 lines removed) |
| VS5 | .env.example DB_PASSWORD → `change_me` |
| IC1 | settings.py docstring retargeted (5436/knowtwin, 8090/3001, 0.1.0) |
| NEW-2 | docker-compose.yml header: ner port → `internal-only` |
| SCHEMA_VERSION | Updated 0.1.0 → 0.2.0 in settings.py |
| CORS | Default origins → localhost:8090,localhost:3001 |
| embeddings comment | ecodb-net → knowtwin-net |

### D. Bugs found and fixed during apply

1. **`symmetric` is a PG reserved word** — init.sql used unquoted `symmetric` as column name in predicates_canonical. Fixed: `"symmetric"`.
2. **`ROUND(double precision, int)` doesn't exist in PG** — entity_coverage view used `ROUND(... * 100, 1)` on a `REAL` result. Fixed: `((... * 100)::numeric, 1)`.

## Test results

```
TEST 1: init.sql on fresh volume
  docker logs knowtwin-db | grep ERROR → (empty) ✅

TEST 2: Table set
  \dt → 47 tables. claims PRESENT, memories ABSENT ✅
  New tables: claims, interview_sessions, verified_documents,
  entity_expected_claims, predicates_canonical, predicate_aliases,
  verifier_reports, deletion_requests, claim_entity_links,
  claim_document_links ✅

TEST 3: Indexes
  idx_claims_embedding, idx_claims_disputed_by → 2 rows ✅

TEST 4: entity_coverage view
  SELECT * FROM entity_coverage LIMIT 0 → compiles, 0 rows ✅

TEST 5: CHECK constraint
  INSERT corroboration_level='bogus' → ERROR 23514 ✅

TEST 6: Predicate seed
  seed_predicates.py → 20/20 inserted, 10 offboarding ✅

TEST 7: Admin regression guard
  /auth/me → {"name":"admin","is_super":true} ✅

TEST 8: Health check
  GET :8090/health → 200, schema_version_target=0.2.0 ✅
```

## Container status

```
knowtwin-api       Up (healthy)
knowtwin-db        Up (healthy)
knowtwin-ner       Up (healthy)
knowtwin-frontend  Up (healthy)
```

## API image

Rebuilt (only COPY layer, pip cached). Same 4.96GB.

## Known issues / debt

- **D-P1.2-1**: API code still references `memories` table throughout (memories.py, search.py, admin.py, etc.) — these endpoints will 500 at runtime. Schema-level complete; API adaptation is a future task (P1.3+).
- **D-P1.2-2**: Predicate embeddings empty (tei not running) — deferred to P1.3.
- **D-P1.1-5**: GLiNER still runtime-loaded from HF cache volume (not baked into ner image).
- **D-P1.1-6**: Health-check ConnectError log spam (embeddings).
- **API_KEY_PREFIX**: Still `ecodb_` — P1.5 per plan.
