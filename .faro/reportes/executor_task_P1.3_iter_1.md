# EXECUTOR_REPORT — P1.3 Embed Gate (iter-1)

**Task**: P1.3 — Embed gate (CRITICAL, week-1 exit gate)
**Executor**: executor-1
**Date**: 2026-07-01
**Status**: COMPLETE — 8/8 tests passed, audit clean

## What was done

### A. claims.py (NEW — 205 lines)

- `POST /claims` → `create_claim()`: INSERT with corroboration_level='draft', embedding=NULL. No embed call.
- `PUT /claims/{id}/promote` → `promote_claim()`: transition matrix enforced, embed gate applied.
  - Level IN `_EMBED_LEVELS` → `embed_text(evidence_text, 'passage')` + atomic UPDATE level+embedding.
  - Level = 'rejected' → embedding=NULL + `DELETE FROM triples WHERE claim_id=$1` (cascade to AGE).
  - Level = 'draft' → embedding=NULL.
  - Fail-soft: on embed failure, neither level nor embedding advances (503, claim unchanged).
  - Idempotent: if embedding already present, skip re-embed (just update level).
  - CAP constraint: interview-only claims blocked from 'validated' (409).
- Gate: explicit `IN` frozenset, never `>=`.
- Transition matrix: `draft→single_source→corroborated→corroborated_by_employee→validated`, `{any}→rejected` (terminal).

### B. worker.py (ADAPT)

- Removed Stage 4 chunk-embed block (lines 296-326).
- Removed circuit breaker (imports, variables, functions).
- Removed dead `EMBED_TIMEOUT` constant and `EMBEDDINGS_URL` import.
- Fixed API_URL default: `ecodb-api` → `knowtwin-api`.
- Updated docstrings: "parse → chunk → GLiNER → graph link (no chunk embedding)".

### C. main.py (ADAPT)

- Added `import claims; app.include_router(claims.router)`.

### D. Dockerfile (ADAPT)

- Added `claims.py` to COPY list.
- Added `COPY api/tests/ ./tests/` for in-container test execution.

### E. test_embed_gate.py (NEW — 8 tests)

EG1-EG7 + audit invariant. Uses TestClient (in-process) + asyncpg (DB verification).

### F. P1.2 iter-2 (Hilo inline fixes)

- BC1: FK claim_entity_links.entity_node_id → nodes(id) CASCADE
- BC2: FK claims.session_id → interview_sessions(id) SET NULL + idx
- IC1: documents.trust_tier CHECK 0-2
- BC3: COMMENT on disputed_by_claim_id
- document_entity_links FK → nodes(id) CASCADE
- All applied on live DB + init.sql edited.

## Test results

```
tests/test_embed_gate.py::test_eg1_draft_no_embed PASSED                 [ 12%]
tests/test_embed_gate.py::test_eg2_promote_single_source_embeds PASSED   [ 25%]
tests/test_embed_gate.py::test_eg3_rejected_clears_embedding PASSED      [ 37%]
tests/test_embed_gate.py::test_eg4_disputed_keeps_embedding PASSED       [ 50%]
tests/test_embed_gate.py::test_eg5_no_chunk_embeddings PASSED            [ 62%]
tests/test_embed_gate.py::test_eg6_draft_disputed_no_embed PASSED        [ 75%]
tests/test_embed_gate.py::test_eg7_promote_reject_no_stale PASSED        [ 87%]
tests/test_embed_gate.py::test_audit_gate_invariant PASSED               [100%]

============================== 8 passed in 4.60s ===============================
```

## Audit SQL

```
chunks_with_embed = 0   ✅ (no chunk ever has a non-NULL embedding)
gate_violators    = 0   ✅ (for every claim, embedding presence matches gate rule)
```

## Static checks

- worker.py: no `embed_text` call, no chunk-embed loop ✅
- claims.py: gate is `in _EMBED_LEVELS` (frozenset), never `>=` ✅

## GPU strategy

1. `docker stop ecodb-embeddings` (freed ~10GB VRAM)
2. `docker compose up -d knowtwin-tei` (booted Jina v4 from HF cache, no re-download)
3. Tests run: 8/8 passed in 4.60s
4. `docker compose stop knowtwin-tei` + `docker start ecodb-embeddings` (GPU restored)

## Bug found during development

- `actor["user_id"]` → should be `int(actor["sub"])`. The JWT payload uses `sub` (string) for user_id. Fixed.

## Known debt

- D-P1.3-1: `pytest` not in requirements.txt / Dockerfile (pip installed at runtime for tests)
- D-P1.2-1: AGE trigger dollar-quote injection (Hilo: fix before P1.7)
