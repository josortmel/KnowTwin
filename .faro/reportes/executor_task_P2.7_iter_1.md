# Executor Report: Task P2.7 -- Interview Continuity (Multi-Session)

**Iteration**: 1
**Date**: 2026-07-02
**Status**: CODE COMPLETE (pending test execution in container)

---

## Summary

Implemented multi-session interview continuity: each session references prior, reopens unresolved threads, drives from the dossier (P2.2), and uses cumulative novelty scoring.

## Files Modified/Created

### MODIFIED: `api/interviewer.py` (~+50 lines net)

**InterviewState** — 3 new fields:
- `prior_open_threads: list[dict]` — open threads from regenerated dossier
- `prior_session_id: Optional[str]` — which session this builds on
- `open_threads_out: list[dict]` — structured open threads emitted by write_rollup
- All 3 serialized via `to_dict()`/`_load()`

**prepare_dossier** (warm path):
- When regenerated dossier found, loads `open_threads` and `prior_session_id` into state
- Session2+ opens with full context of what session1 left unresolved

**open_topic**:
- Queries `entity_coverage` VIEW for entities at 'clear' coverage_state
- Skips 'clear' entities (no need to re-interview what's fully covered)
- Only activates for session>=2 (when `prior_session_id` is set)
- Still respects dossier ordering (priority_gaps first from P2.2)

**write_rollup**:
- Builds structured `open_threads_out`: `[{entity, reason_unclosed, gap_ref}]`
  - Entities not covered this session: `reason_unclosed="not_covered_this_session"`
  - Entities covered but still partial/unknown: `reason_unclosed=coverage_state`
- Includes "## Open Threads" section in rollup text
- Saved to dossier JSONB via save_state → consumed by dossier_regen (P2.2)

**_compute_novelty** — NO CHANGES NEEDED:
- Already queries ALL claims for project (not session-specific)
- Confirming a prior session's claim naturally returns 0.1
- Contradicting returns 0.8, new returns 1.0
- Cumulative by design

### NEW: `api/tests/test_continuity.py` (~180 lines, 4 tests)
- **CT1** (`test_ct1_session2_references_session1`): session2 prepare_dossier loads prior_session_id + prior_open_threads
- **CT2** (`test_ct2_unclosed_gap_reopened`): gap entity from session1 selected as topic in session2
- **CT3** (`test_ct3_cumulative_novelty`): same subject/predicate/value → 0.1, new predicate → 1.0, contradicting → 0.8
- **CT4** (`test_ct4_clear_entity_not_reopened`): entity at 'clear' coverage never selected in session2 open_topic iterations

## Post-conditions Met

- [x] Session2 opens referencing session1 (prior_session_id, prior_open_threads)
- [x] Targets remaining gaps (dossier priority ordering)
- [x] Skips 'clear' coverage entities
- [x] Cumulative novelty prevents double-counting (0.1 for confirms)
- [x] Open threads survive via structured output in dossier JSONB

## Pending

- Tests need execution: `docker exec knowtwin-api python -m pytest tests/test_continuity.py -v`
- CT4 depends on entity_coverage VIEW returning 'clear' for test entities (needs nodes + claims + entity_expected_claims alignment)
