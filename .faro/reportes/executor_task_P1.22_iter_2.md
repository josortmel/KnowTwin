# EXECUTOR_REPORT — P1.22 iter-2: Demo seed fixes

**STATUS:** COMPLETE
**Task:** P1.22 iter-2
**Executor:** executor-1
**Date:** 2026-07-01

## Fixes applied

### FIX 1 [CRITICAL] — Audit gate invariant
- Demo claims now use source_type='seed_demo' (not 'document'/'interview')
- Audit invariant test can exclude seed_demo claims
- curator_post.py updated to recognize 'seed_demo' source_type
- Differentiation: session_id IS NULL = doc-origin, session_id IS NOT NULL = tacit-origin

### FIX 2 [CRITICAL] — Trust tier mapping
- Moved "Carlos decides Banco Norte" from plan_banco_norte (tier=2) → organigrama_equipo (tier=0)
- Moved "Maria Lopez ETL" from wiki_etl (tier=1) → organigrama_equipo (tier=0)
- Moved "Maria Lopez PostgreSQL" from adr (tier=2) → organigrama_equipo (tier=0)
- Result: C1,C2,C4 doc_strength = 1×1.0×(0+1) = 1.0 < 1.5 → resolved_in_favor
- C3 (CloudBase SLA): stays in contrato (tier=2), strength = 3.0 → disputed

### FIX 3 [MEDIUM] — Twin insufficient info query
- Changed "capital of France" → "zxqwj9k7m3p2 completely unrelated nonsense"

## Tests
Full regression: 119 passed, 0 failed.
