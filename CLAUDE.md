# KnowTwin — CLAUDE.md

Fork of EcoDB for offboarding knowledge capture. Client: Manu (Eco Consulting).

## Architecture

6-service Docker Compose: db (PG16+AGE+pgvector) · api (FastAPI) · ner (GLiNER) · tei (Jina-v4) · frontend (React+Vite) · cell (behind profile).

Host ports (coexist with EcoDB): db 5436 · api 8090 · ner internal · tei internal · frontend 3001.

All containers `restart: "no"` — must NOT auto-start with Docker (GPU competition with EcoDB).

## Schema

Consolidated `sql/init.sql` (~1100 lines). NO migration runner. Schema born at final version via docker-entrypoint-initdb.d on empty volume.

Core table: `claims` (not memories) with 5 typed state axes:
- trust_tier (0-2), confidence (0-1), corroboration_level (6-value enum), dispute_state (4-value), freshness_state (3-value)

Key tables: claims, interview_sessions, verified_documents, entity_expected_claims, verifier_reports, deletion_requests, predicates_canonical, predicate_aliases, org_settings.

## Embed Gate (CRITICAL invariant)

Embedding IFF `corroboration_level IN ('single_source','corroborated','corroborated_by_employee','validated')`. Explicit IN-list, NEVER `>=`. draft/rejected = NULL embedding. Gate lives in `claims.py::promote_claim()`.

Chunks NEVER embed (gate moved from ingestion to promotion).

## Auth

4 roles: admin, curator, employee, consumer. check_access deny-by-default fail-closed. API_KEY_PREFIX = "knowtwin_". Production secrets guard (KNOWN_DEV_DEFAULTS frozenset).

## Key Modules

- `claims.py` — CRUD + embed gate + valid_transition state machine
- `curator.py` — pre-interview batch extraction + promote-then-detect
- `curator_post.py` — post-session doc_strength scoring + auto-resolution
- `verifier.py` — read-only QA, different model, never writes claims
- `interviewer.py` — 5-state pure Python state machine (no langgraph)
- `interviews.py` — REST + WebSocket API, session ownership enforced
- `twin.py` — GAMR rewrite for claims, GC1 visibility predicate at all 3 stages
- `coverage.py` — criticality-weighted, entity_coverage VIEW
- `documents.py` — upload + trust_hint, knowtwin_ingest channel
- `worker.py` — parse+chunk pipeline (no embed), in-process
- `org_settings.py` — per-project JSONB settings, config merge on PUT

## Frontend

React 18 + Vite + Tailwind + shadcn/ui + TypeScript. 4 views:
- Setup/Curation (7 panels) — curator/admin
- Interview (chat + voice + WS coverage bar) — employee
- Twin (query + sources + disputes) — consumer
- Settings (drawer, 4 sections) — admin

XSS HARD: 0 dangerouslySetInnerHTML, ALL text via SafeText, ESLint react/no-danger=error. sessionStorage for API key (never localStorage).

## AGE Triggers

PL/pgSQL triggers use `cypher_quote()` helper (chr()-based escaping) + tagged `$cq$` dollar-quoting. AGE 1.5.0 does NOT support parameterized Cypher from PL/pgSQL — only from asyncpg client.

## Graph Name

`knowtwin_graph` everywhere. ZERO `ecodb_graph` refs in api/, sql/, scripts/.

## Git Policy

Remote: github.com/josortmel/KnowTwin.git. Phase 1 pushed 2026-07-02.

## Tests

132 tests across 18 families. 3 TEI-dependent (need GPU). Run: `cd api && DATABASE_URL=$KT_DSN pytest tests/ -q`.

Frontend: `cd frontend && npm run build` (must exit 0).

## Demo

Juan Garcia dataset: `python scripts/seed_demo.py`. 8 docs, 58 entities, 4 contradictions (2 resolved + 1 disputed), 5 star tacit claims. Money-shot: "who runs ETL?" → Andres Martin.

Demo claims tagged `demo_seed` in tags array — excluded from audit gate invariant.

## Docker State

Images built: api 4.96GB, ner 1.77GB (CPU-torch pinned), postgres 804MB, tei 10.1GB. Frontend uses node:22-slim dev server.

GPU: RTX 2080 Ti 11GB. EcoDB embeddings holds ~10GB VRAM. For tei tests: `docker stop ecodb-embeddings` → `docker compose up -d knowtwin-tei` → tests → restore.

## Open Debt

See `Eco_Consulting/Faro/Sesiones/2026-07-01_knowtwin/backlog_deuda.md`. Key:
- LLM injection hardening (D-P1.9-1, D-P1.13-2) — before real LLM
- Curator force-override promote (D-P1.19-1)
- Whisper numba conflict (D-P1.15-1)
- 9 batch audit gaps (C1)

## Phase 1 Status

P1.1–P1.22 + P1.4.5 + P1.25 CODE COMPLETE.

P1.23 (demo rehearsal) and P1.24 (real-human validation) moved to END of Phase 2 — require working frontend chat interface connected to live LLM + backend. Cannot be done until full stack is deployed and LLM provider wired.

Phase 2: 15 tasks + P1.23 + P1.24, blocked by 3 Pepe decisions (scoring weights, GDPR, sensitivity-filter).
