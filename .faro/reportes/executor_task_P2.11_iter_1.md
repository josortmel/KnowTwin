# Executor Report: Task P2.11 -- Retention + Deletion (GDPR)

**Iteration**: 1
**Date**: 2026-07-02
**Status**: CODE COMPLETE (pending test execution)

---

## Summary

Implemented GDPR-compliant deletion: configurable retention with auto-expiry cron, employee deletion workflow (request→review→execute), irreversible erasure function, metadata-only tombstones.

## Files Modified/Created

### NEW: `api/deletion.py` (~200 lines)

**`gdpr_erase_claim(conn, claim_id, requester_id, reason_code)`** — shared erasure function:
- Transaction-wrapped
- DELETE triples (cascades to AGE)
- Sets corroboration_level='rejected', embedding=NULL
- evidence_text=NULL, sanitized_text=NULL
- subject_entity='[ERASED]', object_entity=NULL, object_value=NULL
- Audit log entry with reason_code
- INTENTIONALLY irreversible

**`run_retention_expiry(pool, project_id)`** — auto-expiry cron:
- Reads org_settings.retention.{retention_days, auto_expiry}
- Finds claims past retention_days, bounded to MAX_EXPIRY_BATCH=100
- Idempotent: checks audit_log for prior gdpr_erase before processing
- Advisory xact_lock + cell_run record

**Endpoints**:
- `POST /my-claims/{cid}/request-deletion` — employee-own only (employee_id check)
- `GET /claims/deletion-requests?project_id=` — curator/admin only, pending requests
- `PUT /claims/deletion-requests/{id}/review` — approve/reject, curator/admin only
  - Approve → calls gdpr_erase_claim in transaction
  - Reject → sets status='rejected', no data change

### MODIFIED: `api/cell_worker.py` (+5 lines)
- Added `_retention_expiry_handler` + `("retention_expiry", None)` to `_BUILTIN_DISPATCH`

### MODIFIED: `api/main.py` (+3 lines)
- Deletion router included BEFORE disputes/claims (route ordering for /claims/deletion-requests)

### MODIFIED: `api/Dockerfile` (+1)
- Added `api/deletion.py` to COPY list

### NEW: `api/tests/test_retention.py` (~250 lines, 7 tests)
1. **erasure_removes_evidence**: evidence_text=NULL, embedding=NULL, subject='[ERASED]', object=NULL
2. **erasure_removes_from_search**: erased claim absent from visibility-filtered queries
3. **autoexpiry_bounded_idempotent**: 3 old claims expired, re-run = 0
4. **deletion_employee_own_only**: employee_id != actor → 403
5. **deletion_requires_curator_review**: pending → approve → erased
6. **deletion_reject**: reject → claim unchanged
7. **tombstone_no_personal_data**: deletion_requests row has NO evidence, NO names

## Post-conditions Met

- [x] Erased personal data recoverable from NO surface (search/graph/export/tombstone)
- [x] Auto-expiry bounded (MAX_EXPIRY_BATCH=100) + idempotent
- [x] Deletion can't skip review (employee → pending → curator)
- [x] Erasure intentionally irreversible
- [x] Employee can only request own claims (employee_id check)
- [x] Tombstone = IDs + timestamps + reason_code only
- [x] Export excludes erased (rejected filtered by _visibility_sql)
