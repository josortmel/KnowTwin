# EXECUTOR_REPORT — P1.9: Curator pre-interview (cell_type curator_pre)

**STATUS:** COMPLETE
**Task:** P1.9
**Executor:** executor-1
**Date:** 2026-07-01

## Files touched
1. `api/curator.py` — NEW, curator brain + POST /projects/{id}/curator/run
2. `api/cell_worker.py` — stripped ~1500 lines of EcoDB builtins, kept lifecycle infra
3. `api/main.py` — curator router include
4. `api/Dockerfile` — curator.py in COPY list
5. `api/tests/test_curator_pre.py` — NEW, 5 tests

## Actions

### curator.py (NEW — 390 lines)
- `run_curator_pre(pool, project_id, user_id)`: main pipeline
- `_extract_claims_from_chunk`: LLM-based extraction with _SafeFormatter + token_hex injection defense
- `_promote_claim`: draft → single_source (embed gate)
- `_detect_contradictions`: triple-based (same subject+predicate, different object_value)
- `_identify_gaps`: static {entity_type: [required_predicates]} map
- `_seed_expected_claims`: auto-seed coverage denominators for new entities
- `_write_verified_document`: markdown with [CONTRADICTION], [GAP], [ALERTA stale] markers
- `trust_tier_from_hint`: formal/adr/signed→2, wiki/presentation/email→1, orgchart/other→0
- PROMOTE-THEN-DETECT order enforced (create draft → promote → then contradiction detection)
- POST /projects/{id}/curator/run endpoint (curator/admin gated)

### cell_worker.py (stripped 2071→280 lines, −1791)
- DELETED: consolidation (weekly/monthly/quarterly/yearly), foresight_extraction, skill_distillation
- DELETED: scipy/numpy imports, clustering, narration, EcoDB-specific constants
- DELETED: _fetch_memories, _build_cell_system_prompt, _STYLE_NOTES, main(), __main__
- KEPT: _SafeFormatter, _lock_key, _check_idempotency, _create_run, _complete_run, _fail_run
- KEPT: _llm_call, _llm_call_httpx, _llm_call_with_key, _active_cell, _broadcast_sse
- KEPT: recover_stuck_runs, _load_cell_config, _llm_retry
- REPLACED: _BUILTIN_DISPATCH entries → curator_pre only

## Tests — literal output (5 passed)
```
test_trust_tier_mapping PASSED           — CP4: formal→2/wiki→1/other→0
test_contradiction_detection PASSED      — CP2: doc-vs-doc → both disputed
test_gap_identification PASSED           — CP3: cliente_cuenta w/o decide_en → [GAP]
test_expected_claims_seeded PASSED       — CP5: auto-seed coverage denominators
test_curator_idempotent PASSED           — CP7: advisory lock blocks concurrent run
```

Full regression: 55 passed (health 13 + auth 15 + claims 10 + coverage 5 + twin 7 + curator 5).

## Post-conditions
- PROMOTE-THEN-DETECT order ✓
- trust_tier from trust_hint ✓
- Contradiction detection (triple-based) ✓
- Gap identification (static map) ✓
- entity_expected_claims seeded ✓
- Advisory lock idempotency ✓
- EcoDB builtins deleted (−1791 lines, scipy/numpy removed) ✓

## Debt
- D-P1.9-1: LLM extraction untested end-to-end (monkeypatch approach confirmed by Hilo, real LLM at P1.22+)
- D-P1.9-2: Semantic contradiction detection (embedding similarity) requires tei — deferred
- D-P1.9-3: verified_documents [ALERTA stale] marker test not isolated (requires time-dependent data)
- D-P1.9-4: _check_idempotency still references memory_clusters table (EcoDB vestige in cluster_level branch)
