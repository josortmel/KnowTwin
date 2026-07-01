# EXECUTOR_REPORT — P1.4 Claims API (iter-1)

**Task**: P1.4 — Claims API (CRUD + gate + visibility + security)
**Executor**: executor-1
**Date**: 2026-07-01
**Status**: COMPLETE — 10/10 tests passed

## What was done

### A. claims.py expanded (273 → ~430 lines)

Full CRUD with embed gate, server-authoritative lifecycle, role-based visibility:

- **ClaimCreate lockdown** (`extra="forbid"`): EXCLUDED privileged fields — employee_id, session_id, source_id, trust_tier, confidence, corroboration_level, dispute_state, freshness_state, doc_strength, disputed_by_claim_id, resolved_by_user_id, embedding. Client sets ONLY content + optional sensitivity/tags/criticality.
- **POST /claims**: curator/admin only. Server sets user_id from actor, defaults draft/no-embed.
- **GET /claims/{id}**: visibility predicate per role:
  - consumer: must be IN-list corroboration + public/team sensitivity
  - employee: own claims only (employee_id match)
  - curator/admin: all
- **GET /claims**: list with parameterized filters (project_id required, subject_entity, predicate, corroboration_level, dispute_state). Same visibility predicate. Pagination (limit/offset).
- **PUT /claims/{id}**: curator/admin can change sensitivity, dispute_state, tags, resolution_note. Employee: own claims + tighten-only sensitivity. Audit-logged.
- **DELETE /claims/{id}** (soft): sets corroboration_level='rejected', embedding=NULL, DELETE triples, tombstone preserved. Audit-logged.
- **PUT /claims/{id}/promote**: embed gate (P1.3, preserved).

### B. P1.5 iter-2 inline fixes

- auth.py: 4x "ecodb_" → "knowtwin_" in docstrings/descriptions
- events.py: timing-oracle fix — `==` → `hmac.compare_digest()` on broadcast secret

### C. test_claims.py (NEW — 10 tests)

## Test results

```
test_claim_create_rejects_privileged_fields PASSED
test_embed_gate_inlist PASSED
test_lifecycle_illegal_transition_409 PASSED
test_invariant3_cap PASSED
test_employee_own_filter PASSED
test_sensitivity_visibility PASSED
test_draft_invisible_to_consumer PASSED
test_soft_delete_removes_embedding_and_triples_and_hides PASSED
test_no_sql_injection_in_filters PASSED
test_null_byte_and_maxlen_rejected PASSED

10 passed in 1.63s
```

## Security verification

| Check | Result |
|-------|--------|
| Mass-assignment (privileged fields) | 422 on every privileged field ✅ |
| IDOR on employee_id | Employee sees only own claims (employee_id filter) ✅ |
| Draft leak to consumer | 404 on GET/{id} + absent from list ✅ |
| Restricted leak to consumer | Absent from list ✅ |
| Gate uses IN-list not >= | Static confirmed ✅ |
| SQL injection in filters | Parameterized, table survives ✅ |
| Null byte rejected | 422 ✅ |
| Soft delete clears embedding + triples + audit | Verified ✅ |
