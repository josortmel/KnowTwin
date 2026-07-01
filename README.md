# KnowTwin

Tacit-knowledge capture for offboarding — an independent fork of **EcoDB**, adapted
from a collective-memory graph into a claims-based knowledge-capture system.

> **Status:** P1.1 (structural fork). The domain schema (claims, interview sessions,
> verified documents, predicate governance) lands in P1.2; the embed gate in P1.3.

## Architecture — 6 services

| Service | Host port | Notes |
|---|---|---|
| `knowtwin-db` | 127.0.0.1:5436 | PG16 + pgvector + AGE + pg_trgm. Consolidated `sql/init.sql` (no migration runner). |
| `knowtwin-api` | 8090 | FastAPI. Decoupled from `tei` at boot (`/health` soft-checks embeddings). |
| `knowtwin-ner` | 8093 | GLiNER entity extraction (CPU). |
| `knowtwin-tei` | internal-only | Jina-v4 512-dim embeddings (GPU). |
| `knowtwin-frontend` | 3001 | Scaffold placeholder (real UI at P1.18). |
| `knowtwin-cell` | — (profile `cell`) | Curator/Verifier cell worker. Unadapted until P1.9. |

Host ports are offset to **coexist with a running EcoDB** (5435/8080/8091/8092).

## Fork provenance

Forked from EcoDB with the EcoDB-specific surface stripped: MCP proxy, agent-identity,
metacognition routers (clusters/briefing/foresights/cases/skills/cells), dashboard,
watchdog, eval. See the deep-design docs in the Obsidian vault for the full adaptation map.

## Quick start (dev)

```bash
cp .env.example .env          # then fill KNOWTWIN_ENCRYPTION_KEY + secrets
docker compose up -d          # db, tei, ner, api, frontend
curl http://localhost:8090/health
```

> On a box where EcoDB already holds the GPU, `knowtwin-tei` will OOM — bring up the
> non-GPU core with `docker compose up -d knowtwin-db knowtwin-ner knowtwin-api knowtwin-frontend`.

## License

PolyForm Noncommercial 1.0.0 (inherited from EcoDB). Commercial use requires an
Eco Consulting license.
