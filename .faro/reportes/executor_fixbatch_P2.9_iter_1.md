# Fix Batch Report: P2.9 Fixes

**Date**: 2026-07-02
**Status**: ALL 6 FIXES APPLIED

| Fix | File | Change |
|-----|------|--------|
| F25 | claims.py | PUT /batch moved BEFORE PUT /{claim_id} (was unreachable) |
| F26 | test_claims_batch_export.py | Rewritten: tests hit DB directly, verify state + audit_log entries |
| F27 | claims.py | _csv_safe strips leading whitespace, adds \t and \r to injection chars |
| F28 | claims.py | ALL batch audit_log INSERTs moved INSIDE transactions |
| F29 | claims.py | BatchRequest.ids unique validator (prevents multi-step promotion via dupes) |
| F30 | claims.py | Exception handler returns "internal_error" (no raw exc messages) |
