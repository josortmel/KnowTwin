# Executor Report: Task P2.1 -- Scoring System (LAST BUILD TASK)

**Iteration**: 1
**Date**: 2026-07-02
**Status**: CODE COMPLETE (pending test execution)

---

## Summary

Implemented employee knowledge-contribution scoring: quality-not-quantity, anti-gaming, process-not-person framing. Computed-on-read (never stored). Transparent breakdown.

## Formula

```
score = 100 × (0.40·coverage_contrib + 0.20·contradiction_yield + 0.20·quality − 0.20·gaming_penalty)
```

### Components

| Component | Weight | Description |
|-----------|--------|-------------|
| coverage_contrib | 0.40 | SUM(criticality × novelty) / denominator. Capped per claim. Novelty: single_source=1.0, corroborated variants=0.1 |
| contradiction_yield | 0.20 | Claims involved in disputes / total. Contradiction = value. |
| quality | 0.20 | Proportion with actionability > 0.5 |
| gaming_penalty | -0.20 | Activates above 50% low-novelty share. `max(0, (share-0.5)/0.5)` |

## Files Modified/Created

### NEW: `api/scoring.py` (~140 lines)
- `compute_score(conn, project_id, employee_id) → ScoreResponse`
- Computed-on-read from claims table + entity_expected_claims
- GET /projects/{pid}/employees/{eid}/score — employee=own, curator/admin=any
- GET /projects/{pid}/scores — all employees, curator/admin only

### MODIFIED: `api/main.py` (+3 lines)
- Scoring router included

### MODIFIED: `api/Dockerfile` (+1)
- Added scoring.py to COPY

### NEW: `api/tests/test_scoring.py` (~220 lines, 7 tests)
1. **volume_without_novelty_scores_low**: 50 corroborated < 5 single_source
2. **actionability_quality**: high actionability → higher quality
3. **contradiction_yield**: disputed claims → higher yield
4. **gaming_penalty_activates_above_50pct**: 40% → 0, 67% → >0
5. **breakdown_sums**: score matches formula
6. **employee_sees_own_only**: role check
7. **manager_sees_all**: role check

## Anti-gaming Design

- Novelty from corroboration_level: single_source=1.0 (genuinely new info), corroborated=0.1 (just confirming)
- Gaming penalty activates only above 50% low-novelty threshold (generous baseline)
- Penalty formula: `max(0, (low_share - 0.5) / 0.5)` — linear ramp above threshold
- Result: saying what's already documented hurts score, contributing new knowledge helps

## Process-not-Person Framing

- Score = "tu contribución al proceso" (contribution to the process)
- Never stored as person attribute
- Computed-on-read → always current
- Not in exports (claims export has no score column)
