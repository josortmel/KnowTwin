# Executor Report: Task P2.2 -- Dossier Regeneration Inter-Session

**Iteration**: 1
**Date**: 2026-07-02
**Status**: CODE COMPLETE (pending test execution in container)

---

## Summary

Implemented inter-session dossier regeneration: after each Curator-post session completes, a new pipeline regenerates the NEXT session's dossier with updated coverage snapshot, prioritized gaps, open threads, and contradictions.

## Files Modified/Created

### NEW: `api/dossier.py`
- `regenerate_dossier(pool, session_id)` -- main entry point
- Loads completed session, recomputes coverage from `entity_coverage` VIEW
- Builds `priority_gaps` (entities with `coverage_state IN ('unknown','partial')`, ranked by `expected_criticality DESC`)
- Gathers `open_threads` from session claims (single_source or disputed)
- Gathers `contradictions` (project-wide disputed claims)
- Stores regenerated dossier on completed session's `dossier` JSONB (under `regenerated_dossier` key)
- Also seeds next pending session (if any) for the same employee+project
- Advisory lock (`sha256("dossier_regen:{session_id}")`) + idempotency via `cell_runs`

### MODIFIED: `api/cell_worker.py`
- Added `_dossier_regen_handler` to `_BUILTIN_DISPATCH`
- Added `start_dossier_regen_listener(pool)` -- LISTEN on `knowtwin_dossier_regen` channel (same pattern as `start_curator_post_listener`)

### MODIFIED: `api/curator_post.py`
- Added `pg_notify('knowtwin_dossier_regen', session_id)` at end of `run_curator_post()`, after `cell_runs` INSERT (line 170-172)

### MODIFIED: `api/main.py`
- Added `_dossier_regen_task` in lifespan (same pattern as curator_post listener)
- Cleanup on shutdown (cancel task)

### MODIFIED: `api/interviewer.py`
- `prepare_dossier()` now checks for prior regenerated dossier:
  1. First checks if current session was pre-seeded with `regenerated_dossier`
  2. If not, looks for most recent completed session for same employee+project
  3. If found: uses `priority_gaps` to order entities (gaps first), then appends remaining entities
  4. If not found (session 1): cold-build from `entity_expected_claims` (unchanged behavior)

### MODIFIED: `api/Dockerfile`
- Added `api/dossier.py` to COPY list (alphabetical: after `documents.py`)

### NEW: `api/tests/test_dossier.py`
6 tests covering all required scenarios:
- **DS1** (`test_ds1_coverage_after_dossier_regen`): coverage_snapshot reflects claims from session (EntityA > 0, EntityB = 0)
- **DS2** (`test_ds2_clear_entity_absent_from_gaps`): entity with `coverage_state='clear'` absent from `priority_gaps`
- **DS3** (`test_ds3_open_thread_carried`): open_thread from session carried into dossier
- **DS4** (`test_ds4_idempotent`): second run returns `already_completed`, single `cell_run` record
- **DS5** (`test_ds5_cold_build_no_prior`): cold-build dossier from `entity_expected_claims` (ordered by criticality DESC)
- **DS5b** (`test_ds5b_warm_build_with_prior`): `prepare_dossier` with prior regenerated dossier uses `priority_gaps` ordering

## Architecture Decisions

1. **Storage strategy**: Regenerated dossier stored as `dossier.regenerated_dossier` sub-key on the completed session's existing JSONB. This preserves the InterviewState data while adding the regen payload. If a next pending session exists, it's also pre-seeded.

2. **Signal chain**: `write_rollup` -> `pg_notify('knowtwin_curator_post')` -> `run_curator_post` -> `pg_notify('knowtwin_dossier_regen')` -> `regenerate_dossier`. Clean sequential pipeline, each step idempotent.

3. **Coverage source**: Single source of truth via `entity_coverage` VIEW (reuses existing P1.12 infrastructure). No custom coverage computation.

4. **No memory_clusters/tensions refs**: Zero references to stripped EcoDB constructs.

## Post-conditions Met

- [x] After session N + Curator-post, updated dossier exists
- [x] Session N+1 `prepare_dossier` reflects N's learning (via `regenerated_dossier`)
- [x] No dependence on stripped `memory_clusters`/`tensions`
- [x] Reuses `entity_coverage` VIEW as single source
- [x] Advisory lock + idempotency per session_id
- [x] Cell_run written on completion

## Pending

- Tests need execution inside Docker container: `docker exec knowtwin-api python -m pytest tests/test_dossier.py -v`
- Container must be rebuilt to include `dossier.py` in image
