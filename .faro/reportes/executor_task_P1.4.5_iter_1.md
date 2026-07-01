# EXECUTOR_REPORT — P1.4.5: Settings backend (org_settings)

**STATUS:** COMPLETE
**Task:** P1.4.5
**Executor:** executor-1
**Date:** 2026-07-01

## Files touched
1. `api/org_settings.py` — NEW, GET/PUT /projects/{id}/settings
2. `api/claims.py` — create_claim reads sanitization_defaults
3. `api/main.py` — router include
4. `api/Dockerfile` — org_settings.py in COPY list
5. `sql/init.sql` — org_settings table

## Actions

### org_settings.py
- GET /projects/{id}/settings → returns config JSONB (curator+ gated)
- PUT /projects/{id}/settings → upserts config (admin gated)
- Validates sensitivity values against allowlist
- `get_sanitization_default(conn, project_id, entity_type)` helper for claims.py

### claims.py
- create_claim: when sensitivity is default ("restricted"), looks up subject_entity type in nodes table, then checks org_settings for a sanitization default for that type
- Only overrides if a default is configured AND caller didn't explicitly set sensitivity

### Schema
- `org_settings(project_id PK → projects, config JSONB NOT NULL DEFAULT '{}')`
- Config shape: `{sanitization_defaults: {entity_type: sensitivity}, retention: {expire_days, auto_expiry}}`

## Tests
```
25 passed in 2.46s (test_claims 10 + test_auth 15)
```

## Post-conditions
- GET/PUT gated by check_access (curator/admin) ✓
- Claim-create reads defaults for subject entity type ✓
- Retention config stored, enforcement deferred (P2.11) ✓
- STT config NOT duplicated (lives in cell_task_configs) ✓
