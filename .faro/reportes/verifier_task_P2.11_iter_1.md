```
VERIFIER_STATUS: TEST_COMPLETE
VERSION_TESTED: P2.11 Retention + deletion GDPR (KnowTwin Phase 2)
LOOP: 1

PLAN_TESTS:
  - [PT1] test_retention.py — 7 tests | 2 PASS, 5 FAIL | output:
      test_erasure_removes_evidence FAILED — NotNullViolationError: evidence_text
      test_erasure_removes_from_search FAILED — same
      test_autoexpiry_bounded_idempotent FAILED — same (auto-expiry calls gdpr_erase_claim)
      test_deletion_employee_own_only PASSED
      test_deletion_requires_curator_review FAILED — same
      test_deletion_reject PASSED
      test_tombstone_no_personal_data FAILED — same

      ROOT CAUSE: claims.evidence_text has NOT NULL constraint in schema.
      gdpr_erase_claim (deletion.py:50) tries: evidence_text = NULL
      → asyncpg.NotNullViolationError

      FIX OPTIONS:
      A) ALTER TABLE claims ALTER COLUMN evidence_text DROP NOT NULL
      B) Set evidence_text = '[ERASED]' instead of NULL (keeps NOT NULL invariant)

      Option B is safer: it preserves the NOT NULL constraint (which protects
      other code paths from inserting claims without evidence) and still strips
      personal data. The '[ERASED]' sentinel is already used for subject_entity.

  - [PT2] After erasure: evidence_text, sanitized_text, embedding all NULL | BLOCKED |
      Cannot verify — erasure fails before reaching these assertions.
      Code review: deletion.py:46-57 WOULD set all three to NULL if the NOT NULL
      constraint were removed. The logic is correct, the schema blocks it.

  - [PT3] After erasure: triples deleted | BLOCKED |
      deletion.py:44: DELETE FROM triples WHERE claim_id = $1
      This line runs BEFORE the UPDATE that fails, so in the current transaction
      (which rolls back on error), triples are NOT deleted either.

  - [PT4] After erasure: twin query → no results | BLOCKED |
      Cannot verify — no successful erasure to test against.

  - [PT5] Tombstone: no personal content in deletion_requests | PARTIAL PASS |
      Schema verified: deletion_requests table has NO evidence_text, sanitized_text,
      or embedding columns. Columns: {claim_id, created_at, id, project_id, reason,
      requested_by, resolved_at, reviewed_by, status} — metadata-only. ✓
      But end-to-end test fails due to blocked erasure.

  - [PT6] Employee non-own claim → 403 | PASS |
      deletion.py:145: if claim["employee_id"] != actor_id: raise HTTPException(403)

  - [PT7] auto-expiry retention_days=NULL → 0 expired | PASS | output:
      retention_days=NULL + auto_expiry=True → {"expired": 0, "reason": "auto_expiry_disabled"}
      retention_days=0 → disabled (falsy check)
      retention_days=-1 → disabled (< 0 check)
      auto_expiry=False → disabled
      No org_settings → disabled

STRESS_TESTS:
  - [ST1] NOT NULL constraint vs GDPR erase | **BLOCKER** |
      claims.evidence_text NOT NULL (from init.sql schema)
      deletion.py:50 sets evidence_text = NULL → crash
      EVERY erasure path fails: manual (curator-approved) and auto-expiry

ADDITIONAL_TESTS:
  - [AT1] retention_days=NULL → disabled | PASS
  - [AT2] auto_expiry=False → disabled | PASS
  - [AT3] retention_days=0 → disabled | PASS
  - [AT4] No org_settings → disabled | PASS
  - [AT5] retention_days=-1 → disabled | PASS
  - [AT6] Employee own-claim gate (code review) | PASS
  - [AT7] Tombstone schema: no personal data columns | PASS
  - [AT8] gdpr_erase is transactional | PASS (transaction + triples + [ERASED] + audit)
  - [AT9] MAX_EXPIRY_BATCH = 100 (bounded) | PASS

BUG_HUNTING:
  - [BH1] GDPR erase sets NULL on NOT NULL column | **FAILED** | observations: CRITICAL — all erasure blocked
  - [BH2] Auto-expiry with disabled settings | SURVIVED | observations: 5 disabled scenarios all return 0
  - [BH3] Employee non-own deletion | SURVIVED | observations: employee_id check at line 145
  - [BH4] Tombstone metadata-only | SURVIVED | observations: schema has no personal data columns
  - [BH5] Transaction atomicity | SURVIVED | observations: async with conn.transaction() wraps all changes
  - [BH6] Batch bounded (MAX_EXPIRY_BATCH=100) | SURVIVED | observations: LIMIT in query
  - [BH7] Curator review gate | CODE CORRECT, BLOCKED BY BH1 | observations: deletion_requests → pending → curator reviews
  - [BH8] Idempotency (audit_log check) | CODE CORRECT, BLOCKED BY BH1 | observations: checks audit_log before re-erasing
  - [BH9] Deletion reject preserves claim | SURVIVED | observations: claim unchanged after curator rejection

SUMMARY:
  total_tests: 16
  tests_pass: 11
  tests_fail: 5
  regressions_detected: 0
  active_attacks: 9
  attacks_survived: 7 (2 blocked by BH1)

BETA_TESTER_IMPRESSIONS:

The deletion and retention system is well-designed architecturally. The gdpr_erase_claim function is properly transactional, strips all personal data (evidence_text, sanitized_text, embedding, subject_entity, object_entity, object_value), deletes triples, and creates an audit entry. The deletion_requests table is correctly metadata-only — no personal content stored.

The auto-expiry system is robust: bounded at 100 per batch, idempotent via audit_log check, properly handles all disabled scenarios (NULL days, 0 days, negative days, auto=false, no settings).

However, there is ONE critical blocker: the claims.evidence_text column has a NOT NULL constraint that prevents GDPR erasure from completing. This blocks 5/7 plan tests and means NO claim can actually be erased in the current state.

The fix is straightforward: either DROP NOT NULL from evidence_text, or change the erase function to set evidence_text = '[ERASED]' instead of NULL. Option B (sentinel value) is safer — it preserves the NOT NULL constraint that protects normal insert paths while still stripping personal data.

REQUIRED_FIXES:
  - [BH1] CRITICAL: claims.evidence_text NOT NULL blocks GDPR erasure.
    Fix: either (A) ALTER TABLE claims ALTER COLUMN evidence_text DROP NOT NULL, or
    (B) change deletion.py:50 from evidence_text = NULL to evidence_text = '[ERASED]'
    Recommended: Option B (preserves NOT NULL invariant for other code paths)

OBSERVATIONS:
  - If Option B: also update the test assertions from `is None` to `== '[ERASED]'`
  - predicate column is NOT erased — consider whether it constitutes personal data

VERDICT: REQUEST_CHANGES

NEXT_ACTION: "The Supervisor must fix the NOT NULL vs erasure conflict. Recommended: change deletion.py:50 to set evidence_text = '[ERASED]' instead of NULL. Then re-run verifier."
```
