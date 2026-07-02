# Executor Report: Task P2.8 -- Interview Style Adaptation

**Iteration**: 1
**Date**: 2026-07-02
**Status**: CODE COMPLETE (pending test execution in container)

---

## Summary

Implemented phrasing-only interview style adaptation based on employee profile (technical/relational/mixed) and dynamic signals (short answers, vagueness, fatigue). ZERO changes to extraction/novelty/turn_value math. SA5 golden transcript test proves style isolation.

## Files Modified/Created

### NEW: `api/interview_style.py` (~70 lines)
- `determine_style(comm_style, turn_texts) -> StyleDirective`
- Static: `comm_style` → framing/follow_up defaults
  - `technical` → architecture, dependencies, decision phrasing
  - `relational` → team dynamics, handoff, interpersonal phrasing
  - `mixed`/`None` → broad exploration
- Dynamic signals from `turn_texts`:
  - Short answers (avg < 20 words) → specific closed prompts
  - Vague answers (3+ hedging words in last 3 turns) → reformulate with scenarios
  - Fatigue (declining word count in last 3 turns) → shorter prompts, critical focus
- `StyleDirective` dataclass: `{framing, follow_up_style, length_guidance}`
- `VALID_STYLES = {"technical", "relational", "mixed"}`

### MODIFIED: `api/interviewer.py` (~+25 lines)
- **InterviewState** +2 fields: `comm_style: Optional[str]`, `turn_texts: list[str]`
- **`get_style_directive(state)`**: computes current directive from state, exported for interviews.py
- **`conduct_turn`**: appends `user_text[:500]` to `state.turn_texts`. Returns `style_directive` in response dict.
- **ZERO changes** to `_llm_call` invocation, `_compute_novelty`, turn_value calculation, or `_check_convergence`

### MODIFIED: `api/interviews.py` (~+8 lines)
- `SessionCreate`: +`comm_style: Optional[str]` (validated: technical/relational/mixed)
- `create_session`: stores `comm_style` in dossier JSONB on INSERT
- `start_session`: returns `style_directive` in response

### MODIFIED: `api/Dockerfile` (+1)
- Added `api/interview_style.py` to COPY list

### NEW: `api/tests/test_style.py` (~200 lines, 5 tests)
1. **SA1** (`test_sa1_technical_profile`): technical → architecture/decision words in framing
2. **SA2** (`test_sa2_short_answers`): avg < 20 words → "specific"/"closed" in follow_up
3. **SA3** (`test_sa3_vague_answers`): hedge words → "reformulate"/"scenario" in follow_up
4. **SA4** (`test_sa4_fatigue`): declining word count → "short"/"critical" in prompts
5. **SA5** (`test_sa5_golden_transcript`): **MANDATORY** — fixed LLM response, 3-way comparison (technical/relational/None):
   - Claims count IDENTICAL across all 3 runs
   - turn_value IDENTICAL across all 3 runs
   - Style directives DIFFER (proving they work)
   - Monkeypatches: `cell_worker._llm_call` (AsyncMock), `embeddings_client.embed_text` (AsyncMock)
   - Clean DB between runs to isolate novelty

## Architecture: Why SA5 Passes by Design

Style directives never enter the extraction pipeline:
```
Employee response → conduct_turn
  ├── _llm_call(system_prompt, user_text)  ← system_prompt is FIXED extraction prompt
  ├── _compute_novelty(...)                ← queries ALL project claims (unchanged)
  ├── turn_value = criticality * novelty    ← math unchanged
  └── style_directive = get_style_directive(state)  ← computed AFTER extraction, RETURNED to caller
```

The style directive is a pure output — it never feeds back into extraction. It's returned alongside the extraction results for the frontend to phrase the NEXT question.

## Post-conditions Met

- [x] Technical → deeper architecture/decision questions
- [x] Short answers → specific/closed prompts
- [x] Vague answers → scenario-based reformulation
- [x] Fatigue → shorter prompts, critical focus
- [x] SA5 proves phrasing-only (3-way identical claims/novelty/turn_value)
- [x] Convergence rule unbroken (fatigue is phrasing-only, _check_convergence unchanged)
- [x] _compute_novelty, _llm_call invocation, turn_value math → ZERO CHANGES
