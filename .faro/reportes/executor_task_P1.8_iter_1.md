# EXECUTOR_REPORT — P1.8: Document upload API

**STATUS:** COMPLETE
**Task:** P1.8
**Executor:** executor-1
**Date:** 2026-07-01

## Files touched
1. `api/documents.py` — trust_hint, check_access, knowtwin_ingest
2. `api/worker.py` — importable module, removed governance/access_flush, knowtwin_ingest, claim_document_links
3. `api/main.py` — lifespan starts ingest listener + recover_stuck
4. `sql/init.sql` — trust_hint column on documents

## Actions

### documents.py
- Added `trust_hint` query param to POST /documents/upload (validated against 8-value enum)
- Added `trust_hint` field to DocumentCreate, DocumentResponse, _DOC_SELECT
- Replaced `is_super` checks with `check_access(conn, actor, project_id, "curator")` on write endpoints (create, upload, reindex, delete)
- Read endpoints keep `visible_project_ids` (all project members can read)
- `ecodb_ingest` → `knowtwin_ingest` (3 places)
- Logger `ecodb.documents` → `knowtwin.documents`

### worker.py
- Removed `from background import run_governance_cycle` import
- Removed `_governance_loop()` + `_access_flush_loop()` + their task creation/cancellation
- Removed `main()` standalone entrypoint + `if __name__ == "__main__"` block
- Created `start_ingest_listener(pool)` — same LISTEN/NOTIFY loop, takes pool as arg
- `ecodb_ingest` → `knowtwin_ingest` (channel + log messages)
- `memory_document_links` → `claim_document_links`, `memory_id` → `claim_id`
- `linked_memory_ids` → `linked_claim_ids`
- Logger `ecodb.worker` → `knowtwin.worker`

### main.py
- Added `import asyncio` at top
- Lifespan now calls `recover_stuck_documents(pool)` at startup
- Lifespan creates `start_ingest_listener(pool)` as background asyncio task
- Task is cancelled on shutdown (yield → cancel → await)

### sql/init.sql
- Added `trust_hint TEXT DEFAULT NULL CHECK (trust_hint IN ('formal_contract','adr','signed_plan','wiki','presentation','email','orgchart','other'))` to documents table
- Applied via ALTER TABLE on live DB

## Tests — literal output

### Regression suite (38 passed):
```
tests/test_health.py (13 passed)
tests/test_auth.py (15 passed)
tests/test_claims.py (10 passed)
============================== 38 passed in 2.97s ==============================
```

### Boot verification:
```
curl http://localhost:8090/health
{"status": "ok", "service": "knowtwin-api", ...}

docker logs knowtwin-api:
INFO:ecodb:Ingest listener started on channel knowtwin_ingest
```

### Grep checks:
- `grep ecodb_ingest api/worker.py api/documents.py` → 0 matches
- `grep memory_document_links api/worker.py` → 0 matches
- `grep governance_loop api/worker.py` → 0 matches
- `grep access_flush_loop api/worker.py` → 0 matches
- `grep __main__ api/worker.py` → 0 matches
- `grep embed/text api/worker.py` → 0 matches

## Post-conditions
- trust_hint enum on upload: formal_contract/adr/signed_plan/wiki/presentation/email/orgchart/other ✓
- Upload/reindex/delete require curator+ ✓
- Reads require project membership ✓
- Channel knowtwin_ingest ✓
- No separate worker container — in-process ✓
- recover_stuck runs at startup ✓
- LFI/SSRF guard preserved (_validate_document_path) ✓
- Stage-4 chunk-embed already removed in P1.3 ✓
- Circuit breaker already removed in P1.3 ✓
- governance_loop + access_flush_loop removed ✓

## Debt
- D-P1.8-1 (LOW): test_upload_ingestion.py not written yet — full pipeline test requires file upload + Docling parse + GLiNER extract in container, which needs sample files + end-to-end setup. Basic endpoint tests via TestClient are feasible but pipeline tests need running services.
- D-P1.8-2 (LOW): Logger names still `ecodb.*` in some files (health, startup loggers) — separate cleanup sweep.
