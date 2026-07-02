# Fix Batch Report: P2.2 + P2.6 Consolidated Fixes

**Date**: 2026-07-02
**Status**: ALL 11 FIXES APPLIED

---

## P2.2 Fixes

| Fix | File | Change |
|-----|------|--------|
| F1 | test_dossier.py | Removed vacuous `or len(...) >= 2` from DS5b assertion |
| F2 | test_dossier.py | Changed `== 3` to `>= 3` for demo entity isolation |
| F3 | interviewer.py | Added `if not isinstance(regen, dict): regen = None` type guard (both lookup paths) |
| F4 | dossier.py | Replaced `pg_try_advisory_lock` with `pg_try_advisory_xact_lock` inside `async with conn.transaction()`. Removed manual `pg_advisory_unlock` finally block. |
| F5 | dossier.py | Added UUID validation at top of `regenerate_dossier` |

## P2.6 Fixes

| Fix | File | Change |
|-----|------|--------|
| F6 | disputes.py | resolve_dispute now updates BOTH sides: main claim gets `resolved_{resolution}`, counterpart gets inverse. Both UPDATEs + audit INSERTs inside `async with conn.transaction()`. |
| F7 | disputes.py + twin.py | Counterpart fetches apply sensitivity filter for non-curator/admin: `AND sensitivity IN ('public', 'team')`. Consumer can't see restricted counterparts. Also added `sanitized_text` to twin.py counterpart query. |
| F8 | disputes.py | Null byte check on `body.resolution_note` before any DB access. Transaction wraps all writes. |
| F9 | disputes.py | assign_resolver checks `project_members` table: resolver must be a project member (422 if not). |
| F10 | permissions.py | Deleted dead `can_resolve_dispute()` function (never imported). |
| F11 | test_disputes.py | Rewrote `test_resolved_against_excluded_but_gated`: now queries actual claims from DB, applies the same filter as twin_query, and verifies doc_id is in resolved set but NOT in primary set. |

## Additional cleanup

- `twin.py`: moved `render_evidence` import to module level (was local inside twin_query). Applied render to DisputeVersion.evidence_text in `_assemble_disputes`. Added `role` parameter to `_assemble_disputes`.
