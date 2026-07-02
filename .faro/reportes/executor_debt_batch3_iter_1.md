# Debt Batch 3 Report: Twin cleanup + operational + adversarial fixes

**Date**: 2026-07-02
**Status**: ALL 7 ITEMS APPLIED

---

| # | ID | File | Change |
|---|-----|------|--------|
| 1 | D-P1.16-1 | twin.py | Removed dead `_sanitize_for_llm` + unused `safe_q` + orphaned `html`/`secrets` imports |
| 2 | D-P1.16-2 | twin.py | Already covered — `_graph_expand` uses `vis_sql` which filters draft/rejected for consumers |
| 3 | D-P1.1-6 | main.py | Health check embed failure log suppressed for 60s after first occurrence (backoff dict) |
| 4 | D-P1.8-2 | documents.py | `_sanitize_metrics()` strips `/app/` paths from processing_metrics error strings |
| 5 | D-P1.15-2 | parsers.py | ffprobe timeout → RuntimeError (fail-closed, rejects audio instead of bypassing duration check) |
| 6 | BC1 GDPR | claims.py | GDPR resurrection guard: `evidence_text in (None, "[ERASED]")` → 409 before any promotion (including force) |
| 7 | BC2 filename | curator.py | filename+section_path moved INSIDE delimiter markers (was in instruction zone) |
