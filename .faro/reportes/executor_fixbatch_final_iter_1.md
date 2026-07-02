# FINAL Fix Batch Report: P2.1 Scoring + P2.11 Tests

**Date**: 2026-07-02
**Status**: ALL FIXES APPLIED

---

## P2.1 Scoring Fixes (4)

| Fix | Change |
|-----|--------|
| F38 | Claims query: `!= 'rejected'` → explicit IN-list of verified levels. Draft claims no longer score. |
| F39 | Division-by-zero guard: `COALESCE(NULLIF(SUM(...), 0), 1.0)` |
| F40 | contradiction_yield excludes `resolved_against` (being wrong shouldn't boost score) |
| F41 | test_employee_sees_own_only + test_manager_sees_all: rewritten with actual compute_score calls + real assertions |

## P2.11 Test Fixes (2)

| Fix | Status |
|-----|--------|
| F36 | Already applied in prior batch — verified: evidence_text=='[ERASED]', predicate=='[ERASED]', employee_id=None, session_id=None |
| F37 | Already applied in prior batch — verified: guard condition test + 0 pending requests assertion |
