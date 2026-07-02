# Debt Batch 4 Report: Turn limit + entity sanitization + 6 test gaps

**Date**: 2026-07-02
**Status**: ALL ITEMS APPLIED

---

## VS-B1: Interview MAX_TURNS + duration limit
- `MAX_TURNS = 50` constant added
- conduct_turn checks: `len(turn_values) >= MAX_TURNS` → force close
- Duration check: `elapsed > planned_duration_min × 2` → force close
- Both log reason in rollup, trigger close_topic state

## VS2: Entity name sanitization
- `current_topic` sanitized: strip `\n`, `\r`, `\x00`, truncate 200 chars
- Topic + employee text moved INSIDE delimiter markers (same BC2 pattern)
- Prevents cross-session entity name injection

## Test Gaps (6)

| ID | File | Test |
|----|------|------|
| TG1 | test_embed_gate.py | `test_tg1_embed_fail_soft`: monkeypatch embed_text→503, claim stays draft, embedding NULL |
| TG-P1.4-1 | test_claims.py | `test_employee_tighten_only_sensitivity`: restricted→public=403, team→restricted=200 |
| TG-P1.4-2 | test_claims.py | `test_update_claim_tags`: PUT tags → response updated + audit_log entry |
| TG-P1.5-1 | test_auth.py | `test_ceo_has_admin_access`: role rank hierarchy verified |
| TG-P1.22-1 | test_demo_seed_e2e.py | `test_coverage_view_works`: now asserts coverage_pct > 0 for at least one entity |
| TG-P1.22-2 | test_demo_seed_e2e.py | `test_contradiction_states`: asserts dispute states + Banco Norte decide_en dispute activity |
