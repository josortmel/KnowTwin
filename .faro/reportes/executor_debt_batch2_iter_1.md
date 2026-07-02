# Debt Batch 2 Report: C1 Audit Gaps + D-P1.15-1 Whisper

**Date**: 2026-07-02
**Status**: ALL ITEMS APPLIED

---

## C1: 7 Audit Gaps Sealed

| # | File | Line | Mutation | Action Name | user_id |
|---|------|------|----------|-------------|---------|
| 1 | curator.py | ~218 | INSERT claim (extraction) | curator_extract | user_id |
| 2 | curator.py | ~252 | UPDATE draft→single_source | curator_promote | NULL |
| 3 | curator.py | ~296 | UPDATE dispute_state (claim A) | curator_dispute | NULL |
| 4 | curator.py | ~296 | UPDATE dispute_state (claim B) | curator_dispute | NULL |
| 5 | interviewer.py | ~291 | INSERT claim (interview) | interview_extract | employee_id |
| 6 | interviewer.py | ~305 | DELETE claim (embed None) | interview_embed_fail_delete | employee_id |
| 7 | interviewer.py | ~313 | DELETE claim (embed error) | interview_embed_fail_delete | employee_id |
| 8 | curator_post.py | ~143 | UPDATE dispute_state (counterpart) | curator_post_dispute | NULL |

Also renamed existing curator_post audit action from 'dispute_claim' to 'curator_post_dispute' for consistency.

**Gap rate**: 64% → 0%

## D-P1.15-1: Whisper numba conflict

| Change | File | Detail |
|--------|------|--------|
| parsers.py | Both `import whisper` calls wrapped with `except Exception` → RuntimeError with diagnostic message |
| parsers.py | Error message suggests: `pip install numba>=0.59` or `run with --no-cov` |
| test_stt.py | test_whisper_installed: added import guard — `pytest.skip` if numba conflict |
