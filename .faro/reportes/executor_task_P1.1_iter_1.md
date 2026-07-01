# EXECUTOR_REPORT — Task P1.1 (Fork EcoDB → KnowTwin) — iter 1

- **Executor:** executor-1
- **Supervisor:** Hilo
- **Date:** 2026-07-01
- **STATUS:** `CODE-COMPLETE + PARTIAL-LIVE-VERIFY` (non-GPU core boot-verified; tei live-boot + cell activation deferred as documented debt)

---

## STATUS detail

- **Files:** DONE — full structural fork written and committed LOCAL ONLY (`3c34293`, no push, per GIT POLICY).
- **Live boot:** non-GPU core (db + api + ner + frontend) verified — see tests_output_literal.
- **Deferred (debt, not failure):** `knowtwin-tei` live boot (GPU-blocked, EcoDB holds VRAM → P1.3 gate); `knowtwin-cell` activation (unadapted until P1.9, behind profile `cell`).

---

## files_touched

**Repo:** `C:\Users\Admin\Documents\KnowTwin` (fork source: `C:\Users\Admin\Documents\EcoDB`, read-only).

Created / forked:
- `api/` — 40 Python modules forked from EcoDB `api/` MINUS the strip-list (see below). `api/Dockerfile` rewritten. `api/requirements.txt`, `api/entrypoint.sh` copied as-is. `api/tests/__init__.py` scaffold.
- `ner/` — `server.py` + `Dockerfile` as-is.
- `tei/` — from EcoDB `embeddings/` (`server.py`, `Dockerfile`, `requirements.txt`).
- `langchain/` — from `ecodb-langchain/src/` (reference base for P1.13/P1.16).
- `docker/Dockerfile.postgres` + `docker/ca-certificates.deb` (the .deb was a required build asset initially missed → build fix).
- `sql/init.sql` — NEW minimal consolidated baseline (P1.1). `sql/trigger_age_sync.sql` copied (mounted at P1.2, not P1.1).
- `scripts/` — `seed_predicates.py`, `sync_age.py`, `setup.sh`, `setup.ps1` (EcoDB copies; KnowTwin adaptation deferred).
- `frontend/index.html` — scaffold placeholder.
- `docker-compose.yml`, `.env.example`, `.gitignore`, `README.md` — NEW.
- `.env` — generated dev secrets (gitignored; valid Fernet ENCRYPTION_KEY).
- Deleted from repo root: `KnowTwin_Funcional_v1_2.docx` + `.pdf` (client functional docs, folded into the fork commit).

Surgically edited (not verbatim copies):
- `api/main.py` — removed migration runner from lifespan (KnowTwin = consolidated init.sql, no runner); de-wired 6 metacognition routers; rebranded title + `/health` service = `knowtwin-api`.
- `api/agents.py` — reduced to management-only (identity / observed-identity / tension endpoints + models REMOVED).
- `api/settings.py` — DB/schema/hostnames retargeted to KnowTwin; `knowtwin-tei` added to embeddings SSRF allowlist.
- `api/Dockerfile` — COPY module list rewritten to the reduced set (no dangling refs); dropped the ecodb-langchain pip install (api doesn't need it; cell_worker falls back to httpx).

**STRIP-LIST (not copied / not wired):** `EcoDB/mcp/`; metacognition routers `clusters.py briefing.py foresights.py cases.py skills.py cells.py`; `agent_identity`/observed/tension routes inside agents.py; `dashboard/ watchdog/ eval/ media/`; `migrate_3_0c_entity_links.py`.

---

## actions (mapped to P1.1 plan steps)

1. Created repo tree: `api/ ner/ tei/ langchain/ sql/ docker/ scripts/ frontend/ tests/`.
2. Copied api module set (40) minus strip-list; ner/tei/langchain/docker/scripts.
3. Rewrote `api/Dockerfile` COPY to match reduced module set.
4. Rewrote `docker-compose.yml`: 6 services with offset host ports (db 5436, api 8090, ner 8093, tei internal-only, frontend 3001); `knowtwin-cell` behind profile `cell`; `knowtwin-net`; volumes; env. **api DECOUPLED from tei** (no depends_on) so it boots + `/health` 200 with tei down.
5. Stripped identity from agents.py; removed metacognition include_router blocks from main.py; mcp not copied.
6. Adapted settings.py (DB pool/embeddings/CORS/crypto retained; DB defaults + hostnames retargeted).
7. `.env.example` + generated `.env` with random secrets + Fernet key. Retained `/health`. `git commit` (local only).
8. Boot-verify (non-GPU core): built all 4 images (cold torch/CUDA — see D-P1.1-4); `docker compose up -d` db+api+ner+frontend. Hit ner GLiNER runtime-download stall (D-P1.1-5) → provisioned model from EcoDB's cache volume + bumped ner start_period → ner healthy → api healthy → all 4 tests PASS.

---

## tests_output_literal

> P1.1 `tests` (criterio_de_exito). Boot scope THIS session = non-GPU core (db+api+ner+frontend); tei GPU-deferred, cell profile-deferred (Hilo rulings).

### Image build — ALL 4 BUILT (tei image BUILDS; not booted — GPU deferred)
```
knowtwin-api:0.1.0        10.8GB
knowtwin-ner:0.1.0        8.35GB
knowtwin-postgres:0.1.0   804MB
knowtwin-tei:0.1.0        10.1GB
```

### T1 — `docker compose ps`  → 4 core services running + healthy (tei/cell not started; deferred)  PASS
```
knowtwin-api        running   Up 22 seconds (healthy)
knowtwin-db         running   Up 10 minutes (healthy)
knowtwin-frontend   running   Up 10 minutes (healthy)
knowtwin-ner        running   Up 51 seconds (healthy)
```

### T2 — `curl -sf -o /dev/null -w '%{http_code}' http://localhost:8090/health`  → 200  PASS
```
HTTP 200
{"status": "ok", "service": "knowtwin-api", "api_version": "0.1.0", "schema_version_target": "0.1.0", "embeddings": "degraded", "llm": "off"}
```
(embeddings=degraded = tei down, EXPECTED and tolerated — api decoupled; /health still 200.)

### T3 — `docker compose logs knowtwin-api | grep -iE 'traceback|fatal'`  → EMPTY  PASS
```
<<EMPTY - PASS>>
```
Startup log (only EXPECTED soft warnings, no traceback):
```
INFO:     Application startup complete.
WARNING:ecodb.startup:entity_dictionary cache load failed ... relation "entity_dictionary" does not exist  (minimal schema — soft, by design)
WARNING:ecodb.health:embeddings health check failed: ConnectError  (tei down — soft, /health still 200)
INFO:     127.0.0.1 - "GET /health HTTP/1.1" 200 OK
```

### T4 — `ls KnowTwin/api/identity.py`  (expect NOT FOUND)  PASS
```
identity.py NOT FOUND (correct — EcoDB has no identity.py; identity was in agents.py, stripped)
```

### Regression probe — `/auth/me` (auth stack intact?)
```
auth/me HTTP 401
```
401 (not 500) → auth router loads + rejects unauthenticated cleanly. Full admin-name assertion needs the users/admin seed (P1.2 AS-IS core); exercised at P1.6.

### Static pre-boot checks (already run)
```
py_compile ALL 40 api modules: OK
dangling imports of stripped modules in WIRED path: NONE
  (only cell_worker.py:1929 `from cells import _default_period` — runtime, cell-only, profiled-off → P1.9)
run_migrations in main.py: NONE
metacognition include_router in main.py: NONE
```

---

## post_conditions_check

- `docker compose up` builds+starts core services healthy → **CONFIRMED** (db+api+ner+frontend healthy; tei deferred GPU, cell deferred profile).
- GET :8090/health → 200 → **CONFIRMED** (T2).
- `python -c "import main"` builds app factory no ImportError → **CONFIRMED** (api boots, uvicorn running, `Application startup complete`, /health 200 — full in-container import clean; static py_compile OK on all 40).
- No MCP/agent_identity/metacognition in running app → **CONFIRMED** (not copied / de-wired; identity.py absent).
- DB up with empty schema (real schema P1.2) → **CONFIRMED** (knowtwin-db healthy; init.sql applied = extensions + search_path + knowtwin_graph + schema_version).
- REGRESSION GUARD /auth/me name='admin' → **NOT EXERCISABLE at P1.1** (minimal schema has no users table / admin seed — that seed lands with the AS-IS core at P1.2). auth.py copied UNMODIFIED → admin path structurally intact. Verified at P1.6 (ported test_auth).

---

## naming / library decisions

- Compose service keys = container names = `knowtwin-{db,tei,ner,api,frontend,cell}` so both `docker compose ps` (Name) and `docker compose logs <svc>` resolve.
- AGE graph named `knowtwin_graph` (EcoDB `ecodb_graph` → renamed; graph.py still hardcodes ecodb_graph → adapted at P1.2/P1.6, not exercised at P1.1 boot).
- `ECODB_LLM_PROVIDER=off` in compose for P1.1 (no llama/cell provider) → `/health` llm=off, lifespan LLM init skipped.
- Kept env var NAMES that code reads (`ECODB_LLM_PROVIDER`, `EMBEDDINGS_URL`, etc.) — renaming is an app-code change out of P1.1 scope.
- API key prefix left `ecodb_` (settings) — auth.py untouched (P1.5 scope); changing it risks the admin-path guard + ported test_auth. Documented for P1.5.
- Dropped ecodb-langchain pip install from api image — cell_worker uses httpx fallback (CLAUDE.md: EcoDB doesn't require ecodb-langchain to run).

---

## DISAGREEMENT / plan-vs-reality items (raised to Hilo, ruled)

1. **"exactly 6 services" vs minimal schema** — resolved by Hilo: 6th = `knowtwin-cell`, DEFINED but behind profile `cell` (unadapted until P1.9). All 6 defined; default up = 5 (db/tei/ner/api/frontend).
2. **GPU / tei live boot** — EcoDB holds ~all VRAM (604–695 MB free). Booting a 2nd Jina-v4 would OOM + risk the shared EcoDB. Ruled: build tei image, DEFER live boot to a GPU window / P1.3. api decoupled from tei.

---

## debt (deferred, tracked)

- **D-P1.1-a** `knowtwin-tei` live boot deferred (GPU contention). GATE: P1.3 (embed-gate test needs real tei). Lean: run tei CPU-only for the trivial P1.3 test volume.
- **D-P1.1-b** `knowtwin-cell` unadapted (scipy/metacognition-bound, EcoDB builtin cells not stripped). Activated + adapted at P1.9. Behind profile `cell`.
- **D-P1.1-c** `cell_worker.py:1929` `from cells import _default_period` — runtime import of a stripped module. Cell-only, profiled-off. Cleaned at P1.9 (cell_worker rewrite).
- **D-P1.1-4** *(HIGH value — Hilo)* api image bloat: torch 2.12.1 pulls the full CUDA stack (~3 GB) on a CPU-only service.
  - **PRIMARY FIX (do this):** in `api/requirements.txt` pin torch/triton/nvidia-* to CPU wheels via `--index-url https://download.pytorch.org/whl/cpu` (or CPU extra-index) → ZERO CUDA wheels, image −3 GB, cold build ~15min→~2min on EVERY future api rebuild (P1.4 claims.py and beyond). Beats caching the CUDA wheels (never pulls them).
  - **BUILD-ACCEL (secondary, optional):** add BuildKit cache MOUNTS — `RUN --mount=type=cache,target=/root/.cache/pip` for pip wheels; mount the existing HF cache so the reranker CrossEncoder predownload is skipped not re-fetched (EcoDB has `ecodb_api_hf_cache` with those weights).
  - **CONSTRAINT:** keep the api image SELF-CONTAINED for shipping to Manu — use cache MOUNTS or the CPU-pin, NOT `FROM ecodb-api:0.25.0` as base (couples the fork to EcoDB). Caches accelerate the build; must never become a runtime dependency of the image.
  - **SEQUENCE:** FIRST action after P1.1 sign-off, BEFORE P1.4 — apply pin + ONE rebuild so the fast CPU layer caches. Investigate EcoDB Dockerfile/compose for an existing pip cache mount to reuse. Not touched now (no mid-build restart, per Hilo).
- **D-P1.1-5** *(new — ner model provisioning, mirrors torch story)* `ner/server.py` downloads the GLiNER model (`urchade/gliner_multi-v2.1` + `microsoft/mdeberta-v3-base`) from HF Hub at RUNTIME, unauthenticated + rate-limited → cold boot stalled at 20%, healthcheck (start_period 60s) false-flagged unhealthy → api (depends_on ner:healthy) stuck in Created.
  - **APPLIED NOW (immediate):** copied EcoDB's already-downloaded model from volume `ecodb_api_hf_cache` → `knowtwin_api_hf_cache` (self-contained own volume, no runtime coupling). ner then loaded from cache in ~20s → healthy. Also bumped ner healthcheck `start_period 60s→180s`, `retries 3→5`.
  - **SHIP-CLEAN FIX (do before shipping to Manu):** bake the model into the ner image at build time (`snapshot_download(...)` in `ner/Dockerfile`, like the reranker precache), with `HF_TOKEN` as a build ARG to dodge the unauthenticated rate limit → shipped image is self-contained, zero runtime HF fetch.
- **D-P1.1-e** `sql/trigger_age_sync.sql` copied but NOT mounted at P1.1 (needs nodes/triples). Mounted at P1.2.
- **D-P1.1-f** scripts/setup.* + seed_predicates.py are EcoDB copies — KnowTwin adaptation at P1.2 (seed) / later.
- **D-P1.1-g** API key prefix still `ecodb_` (auth.py untouched) → P1.5.
```
