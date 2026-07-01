# EXECUTOR_REPORT — P1.16: Twin query pipeline (GAMR → claims)

**STATUS:** COMPLETE
**Task:** P1.16
**Executor:** executor-1
**Date:** 2026-07-01

## Files touched
1. `api/twin.py` — NEW, /twin/query pipeline
2. `api/main.py` — router include
3. `api/Dockerfile` — twin.py in COPY list
4. `api/tests/test_twin.py` — NEW, 7 tests

## Actions

### twin.py — focused GAMR pipeline for claims
- **POST /twin/query**: read-only retrieval with citations
- **Stage 1 (semantic)**: vector similarity on claims.embedding with visibility predicate
- **Stage 2 (text)**: ILIKE fallback on subject_entity + evidence_text (word-split), with visibility predicate + IN-list filter
- **Stage 4 (graph expansion)**: claim_entity_links → discover more claims → **RE-APPLIES visibility predicate** (GC1 fix, non-negotiable)
- **Dispute assembly**: groups by subject_entity+predicate, orders by doc_strength DESC
- **Answer**: mandatory citations `[N]`, unknown → "Insufficient information"
- **Injection defense**: _sanitize_for_llm wraps question + claim text with html.escape + token_hex delimiter
- **resolved_against** excluded from primary sources
- **Employee → 403** (denied /twin/query)
- **rate_limit.py**: already ported and applied via middleware (RateLimitMiddleware in main.py)

### Visibility predicate (shared from claims.py)
- consumer → corroboration IN allowed-list AND sensitivity IN (public, team)
- employee → employee_id = actor_id
- curator/admin → all
- PARAMETERIZED (no value interpolation)
- **Applied at EVERY stage** (semantic, text, graph expansion)

## Tests — literal output (7 passed)
```
test_employee_denied_twin_query PASSED
test_consumer_cannot_retrieve_restricted PASSED
test_rejected_and_draft_excluded PASSED
test_disputed_returns_both_versions PASSED
test_resolved_against_excluded PASSED
test_citation_mandatory_or_insufficient_info PASSED
test_twin_is_readonly PASSED
```

Full regression: 50 passed in 4.52s (health 13 + auth 15 + claims 10 + coverage 5 + twin 7).

## Post-conditions
- Consumer cannot retrieve restricted claims ✓
- Graph expansion re-applies visibility predicate (GC1 fix) ✓
- Rejected/draft never surface ✓
- Disputed shows both versions ordered by doc_strength ✓
- resolved_against excluded ✓
- Employee denied /twin/query (403) ✓
- Citations mandatory or "insufficient information" ✓
- Read-only endpoint (GET/PUT/DELETE → 405) ✓

## Debt
- D-P1.16-1: LLM generation stubbed (deterministic citations, no LLM call). Activates when ECODB_LLM_PROVIDER != "off".
- D-P1.16-2: search.py GAMR still references memories/memory_entity_links (dead code, not wired to twin). Full rewrite deferred — twin.py is the live retrieval path.
- D-P1.16-3: Reranker not wired (stage 3). Text results use static score=0.5, graph results 0.3.
