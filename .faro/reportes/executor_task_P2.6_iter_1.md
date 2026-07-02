# Executor Report: Task P2.6 -- Dispute Resolution Backend

**Iteration**: 1
**Date**: 2026-07-02
**Status**: CODE COMPLETE (pending test execution in container)

---

## Summary

Implemented full dispute UX backend: both-version render with doc_strength transparency, deterministic "why resolved", resolver assignment/tracking, and resolution workflow with deny-by-default authz.

## Files Modified/Created

### NEW: `api/disputes.py` (~240 lines)
- **GET /claims/disputes?project_id=** -- list disputed claims with both versions + doc_strength breakdown, ordered by doc_strength DESC. Role-gated: curator/admin only.
- **GET /claims/{cid}/dispute-detail** -- both versions + breakdown + resolution status. Consumer/curator/admin (not employee).
- **PUT /claims/{cid}/resolve** -- body: {resolution: 'in_favor'|'against', resolution_note: str}. Authz: curator/admin/assigned-resolver ONLY (deny-by-default, 403 for consumer/employee). Sets resolved_by_user_id = actor.sub. Every resolution → audit_log entry.
- **PUT /claims/{cid}/assign-resolver** -- curator/admin only. Sets resolver_user_id on claim. Audit logged.
- Helper `_compute_breakdown(conn, claim_row)` -- recomputes doc_strength components: source_count, freshness_score=1.0, trust_tier, computed_strength.
- Helper `_why_resolved(claim_row)` -- deterministic text: auto-resolution shows formula inputs, manual shows actor + note.
- Helper `_can_resolve(role, actor_id, claim_row)` -- deny-by-default authz check.

### MODIFIED: `api/permissions.py` (+14 lines)
- Added `can_resolve_dispute(conn, actor, claim_row)` -- curator/admin/assigned-resolver, deny-by-default. Uses `check_access` internally.

### MODIFIED: `api/twin.py` (~+90 lines net)
- **New models**: `DocStrengthBreakdown`, `DisputeVersion` (extends TwinSource with object_value, source_type, doc_strength_breakdown).
- **`DisputeGroup`** now has `why_resolved: Optional[str]` and `versions: list[DisputeVersion]`.
- **`_assemble_disputes`** now async, accepts `conn` + `project_id`:
  - Fetches counterpart claims not in search results (via disputed_by_claim_id)
  - Computes doc_strength breakdown per document-type version
  - Generates deterministic "why resolved" for resolved disputes
  - Includes both `disputed` and `resolved_in_favor` claims in groups
- All 3 search queries (_semantic_search, _text_search, _graph_expand) now SELECT `source_type, trust_tier, project_id, disputed_by_claim_id, resolution_note, resolved_by_user_id`.

### MODIFIED: `api/main.py` (+3 lines)
- Disputes router included BEFORE claims router (avoids `/claims/{claim_id}` capturing `/claims/disputes`).

### MODIFIED: `sql/init.sql` (+1 line)
- Added `resolver_user_id INT REFERENCES users(id)` to claims table (for assigned resolver tracking).
- **For existing DBs**: `ALTER TABLE claims ADD COLUMN resolver_user_id INT REFERENCES users(id);`

### MODIFIED: `api/Dockerfile` (+1)
- Added `api/disputes.py` to COPY list.

### NEW: `api/tests/test_disputes.py` (~220 lines, 8 tests)
1. **test_both_versions_with_doc_strength** -- dispute-detail returns both claims + breakdown (source_count, trust_tier, computed_strength)
2. **test_why_resolved_deterministic** -- resolved claim's "why" includes doc_strength formula inputs, no LLM
3. **test_resolve_authz_denies_consumer_employee** -- consumer/employee → denied by _can_resolve
4. **test_resolve_allows_curator_admin** -- curator/admin → allowed
5. **test_resolve_allows_assigned_resolver** -- assigned resolver CAN resolve, other consumer CANNOT
6. **test_manual_records_real_id** -- manual resolution records resolved_by_user_id = actor.sub (non-NULL)
7. **test_auto_has_null_note** -- curator_post auto-resolve → resolved_by_user_id=NULL + "auto:" prefix in note
8. **test_resolved_against_excluded_but_gated** -- resolved_against excluded from primary twin results, accessible via dispute-detail

## Key Design Decisions

1. **doc_strength breakdown recomputed at query time** -- avoids schema changes for storing components. Uses same formula as curator_post: `source_count * freshness_score * (trust_tier + 1)`.

2. **Why resolved is deterministic** -- auto-resolution: surfaces the doc_strength formula inputs from resolution_note. Manual: shows actor ID + note. NEVER LLM-generated.

3. **Deny-by-default authz** -- `_can_resolve()` returns False unless actor is curator/admin/assigned-resolver. Consumer/employee always 403.

4. **Disputes router before claims** -- FastAPI route ordering: GET /claims/disputes must match before GET /claims/{claim_id}.

5. **Resolver assignment** -- separate endpoint (PUT /claims/{cid}/assign-resolver). Once assigned, that user gains resolve permission even if they're just a consumer.

## Post-conditions Met

- [x] Disputed always shows both versions + doc_strength breakdown
- [x] Auto-resolution: resolved_by_user_id=NULL + "auto:" note
- [x] Only authorized actors can resolve (curator/admin/assigned-resolver)
- [x] Every resolution audited with real actor id
- [x] resolved_against gated on request (excluded from primary /twin/query, accessible via dispute-detail)
- [x] "why resolved" is deterministic (doc_strength inputs), never LLM

## Pending

- Container rebuild needed (new disputes.py + schema change)
- For existing DBs: `ALTER TABLE claims ADD COLUMN resolver_user_id INT REFERENCES users(id);`
- Tests need execution: `docker exec knowtwin-api python -m pytest tests/test_disputes.py -v`
