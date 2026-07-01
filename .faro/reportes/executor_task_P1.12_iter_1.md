# EXECUTOR_REPORT — P1.12: Coverage model (calc + API)

**STATUS:** COMPLETE
**Task:** P1.12
**Executor:** executor-1
**Date:** 2026-07-01

## Files touched
1. `api/coverage.py` — NEW, GET /twin/coverage + GET /graph/entities
2. `api/main.py` — router include
3. `api/Dockerfile` — coverage.py in COPY list
4. `api/tests/test_coverage.py` — NEW, 5 hand-computed tests

## Actions

### coverage.py
- GET /twin/coverage: queries entity_coverage view, returns per-entity + overall coverage
- GET /graph/entities: entities with coverage_state (filterable)
- Both consumer/curator/admin gated via check_access
- Project-scoped

### Formula (implemented in entity_coverage VIEW, queried by API)
- numerator = SUM(claim.criticality) WHERE corroboration_level IN allowed-list
- denominator = expected_count × expected_criticality
- coverage_pct = ROUND((num / denom × 100)::numeric, 1)
- States: unknown (0 claims), disputed, validated, clear (≥50%), partial, stale

## Tests — literal output (5 passed)
```
test_coverage_zero_pre_claims PASSED        — 0 claims → unknown, pct=0.0
test_coverage_two_claims_hand_computed PASSED — crit 0.9+0.6=1.5, denom=5.0 → pct=30.0
test_coverage_draft_excluded PASSED         — draft claim → pct unchanged (30.0)
test_coverage_disputed_included PASSED      — disputed@single_source crit 0.5 → pct=40.0
test_coverage_entities_filter PASSED        — GET /graph/entities?coverage_state=unknown works
```

Hand-computed values match exactly: 30.0, 30.0, 40.0.
