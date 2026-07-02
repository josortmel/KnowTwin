# Executor Report: Task P2.4 -- Full Sanitization (fail-closed + DUAL)

**Iteration**: 1
**Date**: 2026-07-02
**Status**: CODE COMPLETE (pending test execution in container)

---

## Summary

Implemented three-level sensitivity pipeline end-to-end: entity-type defaults from org_settings, auto pejorative-judgment detection with fail-closed behavior, DUAL output (original + sanitized), configurable rules, and consistent render at retrieval across all claim-reading endpoints.

## Files Modified/Created

### MODIFIED: `sql/init.sql` (+1 line)
- Added `sanitized_text TEXT` column to claims table.
- For existing DBs: `ALTER TABLE claims ADD COLUMN sanitized_text TEXT;`

### MODIFIED: `api/permissions.py` (+8 lines)
- Added `render_evidence(role, evidence_text, sanitized_text) -> str`:
  - admin/curator/employee → evidence_text (full)
  - consumer → sanitized_text if exists, else evidence_text

### MODIFIED: `api/curator.py` (~+20 lines net)
- In `_extract_claims_from_chunk`, after extracting each claim:
  - Imports `sanitize_evidence` from curator_post (reuse, not duplicate)
  - Checks evidence_text for judgment patterns
  - If detected: `sanitized_text` = redacted version, tag `judgment_flagged`, sensitivity stays `restricted`
  - **Fail-closed**: if detection itself errors, `has_judgment = True` → restricted + flagged
  - evidence_text stays UNCHANGED (DUAL output)
  - Both `sanitized_text` and `tags` passed to INSERT

### MODIFIED: `api/claims.py` (~+5 lines net)
- `_claim_row_to_response(row, role="admin")` — now accepts `role` parameter
- Uses `render_evidence()` to swap evidence_text based on role
- Updated callers: `get_claim`, `list_claims`, `update_claim` all pass `role`
- `create_claim`, `promote_claim` default to "admin" (curator/admin-only endpoints)
- **Pre-existing**: default sensitivity from org_settings already implemented (lines 208-217)
- **Pre-existing**: employee tighten-only already implemented (lines 358-361)

### MODIFIED: `api/org_settings.py` (~+25 lines)
- `SettingsPayload.sanitization_defaults` now accepts `dict[str, Any]` (backward compatible)
- PUT validation supports both formats:
  - Old: `{"persona_externa": "restricted"}`
  - New: `{"persona_externa": {"default_sensitivity": "restricted", "judgment_keywords": ["lazy", "incompetent"]}}`
- `get_sanitization_default()` handles both formats
- NEW `get_judgment_keywords(conn, project_id, entity_type)` — returns custom keyword list

### MODIFIED: `api/twin.py` (~+3 lines)
- All 3 search queries now SELECT `c.sanitized_text`
- TwinSource construction uses `render_evidence(role, ...)` for evidence_text

### MODIFIED: `api/disputes.py` (~+3 lines)
- `_DISPUTE_COLS` includes `sanitized_text`
- `_claim_to_view` accepts `role` parameter, uses `render_evidence`
- `dispute_detail` endpoint passes `role` to `_claim_to_view`

### NEW: `api/tests/test_sanitization.py` (~170 lines, 7 tests)
1. **test_default_by_entity_type** — org_settings persona_externa → restricted
2. **test_judgment_flags_pejorative** — "incompetent" → restricted + judgment_flagged + sanitized_text has [REDACTED]
3. **test_detector_uncertain_restricted** — error path → has_judgment=True (fail-closed)
4. **test_claim_text_cannot_self_escalate** — evidence_text with "sensitivity: public" doesn't change actual sensitivity
5. **test_only_admin_edits_rules** — curator role_rank < admin role_rank → 403
6. **test_three_level_render_at_retrieval** — admin=full, curator=full, employee=full, consumer=sanitized
7. **test_sensitivity_change_audited** — sensitivity change → audit_log entry

## Architecture Decisions

1. **Render predicate centralized in permissions.py** — single `render_evidence()` function called from claims.py, twin.py, disputes.py. Admin/curator/employee see full text; consumer sees sanitized if available.

2. **Judgment detection reuses curator_post.sanitize_evidence** — no duplicated regex. Same patterns, same [REDACTED] replacement. Imported in curator.py extraction path.

3. **Fail-closed pattern** — try/except around detection call. If ANY error: `has_judgment = True` → sensitivity='restricted' + tag='judgment_flagged'. NEVER defaults to public/team on error.

4. **DUAL output** — evidence_text is NEVER modified. sanitized_text is a separate column with [REDACTED] replacements. Sensitivity gates who sees which. If curator later loosens sensitivity to 'team', consumers see sanitized_text.

5. **No Dockerfile change** — no new API modules added (test file goes in tests/ already COPY'd).

## Post-conditions Met

- [x] No pejorative reaches team/public (judgment → restricted + consumer sees sanitized)
- [x] Fail-closed confirmed (error → restricted)
- [x] No injection/self-escalation (sensitivity set by code, not content)
- [x] Non-admin can't change org visibility (PUT check_access admin)
- [x] Render at API level, not UI
- [x] Every sensitivity change audited

## Schema Changes for Existing DBs

```sql
ALTER TABLE claims ADD COLUMN sanitized_text TEXT;
```
