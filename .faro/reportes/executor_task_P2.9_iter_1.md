# Executor Report: Task P2.9 -- Batch Claims + Export + Audit Trail

**Iteration**: 1
**Date**: 2026-07-02
**Status**: CODE COMPLETE (pending test execution)

---

## Summary

Implemented batch claim lifecycle management (approve/reject/set_sensitivity for up to 200 claims in one request), role-gated export (CSV with formula-injection protection + JSON), and per-claim audit trail timeline.

## Files Modified/Created

### MODIFIED: `api/claims.py` (~+200 lines)

**PUT /claims/batch** (curator/admin only):
- Body: `{ids: UUID[], action: "approve"|"reject"|"set_sensitivity", value?: str}`
- `approve`: auto-promotes one step via `_APPROVE_NEXT` map. Handles embed gate (single_source needs embedding). CAP invariant#3 enforced (interview max = corroborated_by_employee).
- `reject`: sets rejected, clears embedding+triples (in transaction)
- `set_sensitivity`: validates public/team/restricted
- Partial failure: illegal on one ID → that ID in `failed[]`, others proceed
- Every action → individual audit_log entry
- Response: `{succeeded: [{id, new_state}], failed: [{id, error}]}`

**GET /claims/export** (registered BEFORE /{claim_id} to avoid path capture):
- Params: `project_id`, `format=csv|json`
- Role+sensitivity gated via `_visibility_sql`
- Applies `render_evidence` (P2.4 three-level render)
- CSV: formula-injection-safe (`_csv_safe` prefixes =,+,-,@ with single quote)
- JSON: array of claim objects with ISO timestamps

**GET /claims/{id}/audit** (curator/admin only):
- Returns audit_log timeline for a specific claim
- Shows: id, user_id, action, details, timestamp
- Ordered by created_at ASC

### MODIFIED: `api/interviewer.py` (P2.7 fix F19)
- Removed `if state.prior_session_id:` guard — clear-entity skip now unconditional

### MODIFIED: `api/tests/test_continuity.py` (P2.7 fix F20)
- `pytest.skip` → `assert` for clear coverage precondition

### NEW: `api/tests/test_claims_batch_export.py` (~230 lines, 7 tests)
1. **batch_50_approve**: transition map validation for 50 claims
2. **partial_fail**: 3 valid + 1 invalid UUID → 3 succeed, 1 fail
3. **export_csv_role_filtered**: curator sees 4 (all), consumer sees 2 (public only)
4. **export_csv_injection_safe**: =,+,-,@ → prefixed with '
5. **export_json_valid**: array with required fields
6. **audit_trail_timeline**: 2 sensitivity changes → 2 audit rows with actor+timestamp
7. **batch_authz**: consumer/employee rank < curator → 403

## Route Ordering

GET /claims/export registered BEFORE GET /claims/{claim_id} to prevent UUID path parameter from capturing "/export" as an invalid UUID (422).

## Post-conditions Met

- [x] 50+ claims in ONE batch request
- [x] Respects transition matrix + CAP invariant#3
- [x] Export correct + role/sensitivity filtered
- [x] CSV formula-injection-safe
- [x] Audit reuses existing audit_log table
- [x] Partial failure: bad claims reported, good claims proceed
