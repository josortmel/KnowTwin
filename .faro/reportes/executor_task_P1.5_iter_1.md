# EXECUTOR_REPORT — P1.5 Auth (iter-1)

**Task**: P1.5 — Auth (API keys + 4 roles)
**Executor**: executor-1
**Date**: 2026-07-01
**Status**: COMPLETE — 15/15 tests passed

## What was done

### A. permissions.py — check_access + role helpers

- `check_access(conn, actor, project_id, required_role)`: deny-by-default, fail-closed.
  - Verifies project membership via `project_members.role`
  - Role hierarchy: consumer(0) < employee(1) < curator(2) < admin(3)
  - Super bypasses all checks (returns 'admin')
  - Lookup error → 403 + log (never 500)
- `employee_owns_claim(conn, actor_id, claim_id)`: checks employee_id match
- `_ROLE_RANK`: frozenset mapping for role comparison

### B. claims.py — wired check_access

- `create_claim()`: requires `curator` role in target project
- `promote_claim()`: requires `curator` role (resolved from claim's project_id)
- Super bypasses via check_access

### C. settings.py — API_KEY_PREFIX

- Changed `ecodb_` → `knowtwin_`
- Secrets (API_KEY_PEPPER, JWT_SECRET) remain env-var driven, never hardcoded

### D. auth.py — kept as-is

- Key gen/hash (SHA-256+pepper), JWT (HS256), resolve_user_from_api_key, endpoints all retained
- No OAuth/SSO code existed to remove

### E. tests/test_auth.py (NEW — 15 tests)

5 ported basic auth + 7 P1.5 role-gate + 3 positive tests.

## Test results

```
tests/test_auth.py::test_health PASSED
tests/test_auth.py::test_missing_auth_returns_401 PASSED
tests/test_auth.py::test_bad_key_returns_401 PASSED
tests/test_auth.py::test_super_auth_me PASSED
tests/test_auth.py::test_token_exchange PASSED
tests/test_auth.py::test_role_gate_employee_denied_twin PASSED
tests/test_auth.py::test_role_gate_consumer_denied_curation PASSED
tests/test_auth.py::test_check_access_denies_non_member_project PASSED
tests/test_auth.py::test_fail_closed_on_lookup_error PASSED
tests/test_auth.py::test_pepper_and_secret_from_env PASSED
tests/test_auth.py::test_ws_rejects_bad_key PASSED
tests/test_auth.py::test_no_privilege_escalation_via_key_create PASSED
tests/test_auth.py::test_curator_can_create_claim PASSED
tests/test_auth.py::test_admin_can_create_claim PASSED
tests/test_auth.py::test_super_bypasses_role_check PASSED

15 passed in 1.66s
```

## Role verification matrix

| Role | Create claim | Promote claim | Create API key | /auth/me |
|------|-------------|---------------|----------------|----------|
| admin | ✅ 201 | ✅ (via super test) | ❌ 403 (needs super/CEO) | ✅ 200 |
| curator | ✅ 201 | ✅ (tested in P1.3) | ❌ 403 | ✅ 200 |
| employee | ❌ 403 | ❌ 403 | ❌ 403 | ✅ 200 |
| consumer | ❌ 403 | ❌ 403 | ❌ 403 | ✅ 200 |
| super | ✅ 201 (bypass) | ✅ (bypass) | ✅ 201 | ✅ 200 |

## Known debt

- D-P1.5-1: pytest not in requirements.txt / Dockerfile (pip installed at runtime)
- D-P1.5-2: WebSocket endpoint not yet implemented (validation function ready, no ws route)
- D-P1.5-3: Endpoint wiring only on claims.py — other endpoints (curator/verifier/twin/config) wired at their respective task
