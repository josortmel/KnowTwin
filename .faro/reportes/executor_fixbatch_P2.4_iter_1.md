# Fix Batch Report: P2.4 Remaining Fixes

**Date**: 2026-07-02
**Status**: ALL 6 FIXES APPLIED

| Fix | File | Change |
|-----|------|--------|
| F13 | twin.py | `_format_answer` now accepts `role`, applies `render_evidence` to evidence_text before truncation |
| F14 | curator_post.py | Writes to `sanitized_text` instead of overwriting `evidence_text`. Original preserved (DUAL model). |
| F15 | disputes.py | list_disputes passes `role` to `_claim_to_view` for both claim and counterpart |
| F16 | permissions.py | `if sanitized_text:` → `if sanitized_text is not None:` (empty string preservation) |
| F17 | curator.py | Exception path now sets `sanitized_text = "[Evidence under review]"` (prevents leak on later sensitivity change) |
| F18 | org_settings.py | Deleted dead `get_judgment_keywords()` function |
