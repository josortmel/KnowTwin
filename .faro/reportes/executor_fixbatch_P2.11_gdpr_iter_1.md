# CRITICAL Fix Batch Report: P2.11 GDPR Comprehensive Erasure

**Date**: 2026-07-02
**Status**: ALL 7 FIXES APPLIED
**Priority**: CRITICAL — adversarial-found PII leaks

---

## Fixes Applied

| Fix | Severity | Change |
|-----|----------|--------|
| F32 | CRITICAL | gdpr_erase_claim: expanded UPDATE to erase ALL PII columns (predicate, employee_id, user_id, session_id, resolution_note, resolved_by_user_id, resolver_user_id, disputed_by_claim_id, tags) |
| F33 | CRITICAL | Added DELETE FROM claim_entity_links + claim_document_links INSIDE transaction BEFORE UPDATE |
| F34 | CRITICAL | Clean related interview_session: rollup → '[Session data erased per GDPR request]', strip turn_texts + entities_seen from dossier JSONB |
| F35 | HIGH | review_deletion_request: NULL out reason field after approval (reason can contain PII) |
| F36 | MEDIUM | test assertions: evidence_text=='[ERASED]', predicate=='[ERASED]', employee_id=None, session_id=None |
| F37 | MEDIUM | test_deletion_employee_own_only: now verifies guard condition + asserts no pending request created |

## Erasure Surface Coverage (post-fix)

| Surface | Pre-fix | Post-fix |
|---------|---------|----------|
| claims.evidence_text | '[ERASED]' | '[ERASED]' ✓ |
| claims.subject_entity | '[ERASED]' | '[ERASED]' ✓ |
| claims.predicate | KEPT (PII!) | '[ERASED]' ✓ |
| claims.employee_id | KEPT (PII!) | NULL ✓ |
| claims.user_id | KEPT | NULL ✓ |
| claims.session_id | KEPT (link to PII!) | NULL ✓ |
| claims.resolution_note | KEPT (can have PII!) | NULL ✓ |
| claims.resolved_by/resolver | KEPT | NULL ✓ |
| claims.disputed_by_claim_id | KEPT | NULL ✓ |
| claims.tags | KEPT | '{}' ✓ |
| claim_entity_links | KEPT (entity associations!) | DELETED ✓ |
| claim_document_links | KEPT | DELETED ✓ |
| interview_sessions.rollup | KEPT (contains evidence!) | '[Session data erased...]' ✓ |
| interview_sessions.dossier.turn_texts | KEPT (raw answers!) | STRIPPED ✓ |
| interview_sessions.dossier.entities_seen | KEPT | STRIPPED ✓ |
| deletion_requests.reason | KEPT (can have PII!) | NULL on approve ✓ |

## Verification SQL (post-deployment)

```sql
-- 1. No PII on erased claims
SELECT employee_id, predicate, session_id FROM claims WHERE subject_entity = '[ERASED]';
-- Expected: all NULL/[ERASED]

-- 2. No entity links
SELECT count(*) FROM claim_entity_links WHERE claim_id IN (SELECT id FROM claims WHERE subject_entity = '[ERASED]');
-- Expected: 0

-- 3. Session rollup erased
SELECT rollup FROM interview_sessions WHERE id IN (...);
-- Expected: '[Session data erased per GDPR request]'

-- 4. Deletion request reason NULLed
SELECT reason FROM deletion_requests WHERE status = 'approved';
-- Expected: all NULL
```
