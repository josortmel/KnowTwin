# KnowTwin

**Capture tacit knowledge before it walks out the door.**

KnowTwin captures undocumented knowledge from departing employees through AI-guided interviews, structures it as a navigable knowledge graph, and serves it via a digital twin that answers questions with citations and provenance.

## What it does

1. **Upload documents** — contracts, org charts, wikis, runbooks
2. **AI Curator extracts claims** — structured knowledge with entity linking and contradiction detection
3. **Interview the employee** — AI-guided conversation that probes knowledge gaps, detects contradictions against documentation, and extracts tacit claims
4. **Query the Twin** — natural language answers about the employee's knowledge, with citations, dispute handling, and confidence scoring

## Quick start (~15-30 minutes first run)

> **WARNING:** You MUST create `.env` from `.env.example` before starting. Default secrets are insecure. After loading demo data, generate your own API key with `python bootstrap_first_apikey.py`.

### Prerequisites

- **Docker Desktop** with Compose v2
- **NVIDIA GPU** with 11+ GB VRAM (for Jina-v4 embeddings)
- **Node.js 18+** (for Electron desktop app)
- **Git**

### 1. Clone and configure

```bash
git clone https://github.com/josortmel/KnowTwin.git
cd KnowTwin
cp .env.example .env
```

Edit `.env` and set:
```bash
# REQUIRED — generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
KNOWTWIN_ENCRYPTION_KEY=<your-fernet-key>

# REQUIRED — change these for production
KNOWTWIN_DB_PASSWORD=<strong-password>
KNOWTWIN_JWT_SECRET=<random-32-bytes>
KNOWTWIN_API_KEY_PEPPER=<random-32-bytes>

# OPTIONAL — HuggingFace cache to avoid re-downloading Jina v4 (~7GB)
HF_CACHE_PATH=/path/to/your/.cache/huggingface
```

### 2. Start the stack

```bash
docker compose up -d
```

Wait for services to be healthy (~3-5 minutes, longer on first run for model downloads):

```bash
docker compose ps
# knowtwin-db, knowtwin-api, knowtwin-ner should show "healthy"
# knowtwin-tei takes longer (GPU model load, ~2-3 min)
```

Verify:
```bash
curl http://localhost:8090/health
# {"status":"ok","embeddings":"ok","llm":"ok"}
```

> **Note:** The frontend runs as an Electron desktop app (Step 5), not as a Docker service.

### 3. Load demo data

```bash
# Generate your first API key
docker exec knowtwin-api python bootstrap_first_apikey.py
# Save the key — it won't be shown again

# Load the Juan Garcia demo dataset (379 claims, 203 graph edges)
docker exec knowtwin-db psql -U knowtwin -d knowtwin -f /seed/demo_data.sql

# Rebuild the Apache AGE graph from SQL triples
docker cp scripts/sync_age.py knowtwin-api:/app/sync_age.py
docker exec knowtwin-api python sync_age.py
```

### 4. Configure LLM provider

Open the app and go to **Agent Config**:
1. Add a provider (DeepSeek, OpenAI, or Anthropic)
2. Enter your API key (stored encrypted, never in git)
3. Select a model for each agent (curator, verifier, interviewer)

Or via API:
```bash
curl -X POST http://localhost:8090/api/v1/providers \
  -H "Authorization: Bearer <your-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"provider": "deepseek", "api_key": "<your-deepseek-key>"}'
```

### 5. Install and launch the desktop app

```bash
cd frontend
npm install
npm run dev
```

The app opens at **Processes** — your offboarding command center.

#### Offboarding flow

| Step | What to do | Where |
|------|-----------|-------|
| 1. Create process | Enter employee name, role, department, exit date, manager, replacement | **Processes** → New process |
| 2. Upload documents | Contracts, org charts, wikis, runbooks — with trust level per source | **Setup** → Documents |
| 3. Process documents | AI extracts knowledge items from uploaded files | **Setup** → Documents → Process documents |
| 4. Interview employee | AI-guided sessions that probe knowledge gaps and detect contradictions | **Interviews** → New session (suggested topics from gaps) |
| 5. Review findings | Approve, promote, or reject extracted knowledge items | **Setup** → Curation Inbox |
| 6. Resolve contradictions | Side-by-side comparison of conflicting claims with resolution notes | **Decisions** → Contradictions |
| 7. Query the assistant | Ask questions about the employee's knowledge — natural language answers with citations | **Knowledge Assistant** |
| 8. Monitor progress | Track completeness, open contradictions, days until exit | **Processes** → click process |

#### Navigation

The nav bar is organized by function:

**Offboarding** — the HR workflow
- **Processes** — active offboardings with progress, traffic lights, and next steps
- **Setup** — document upload, curation inbox, agent configuration
- **Interviews** — AI-guided knowledge transfer sessions
- **Knowledge Assistant** — conversational interface to the captured knowledge
- **Decisions** — contradictions, deletions, stale items, alias review, history

**Knowledge** — explore what's been captured
- **Dashboard** — system overview with stats, attention inbox, activity feed
- **Explorer** — browse and search knowledge items with filters
- **Graph** — visual knowledge graph (force-directed, interactive)
- **Ingestion** — document processing pipeline status

**Governance** — manage the knowledge structure
- **Ontology** — entity dictionary, predicates, alias management, merge flow

#### Build for production

```bash
cd frontend
npm run build          # TypeScript check + Vite production build
npm run package        # Electron Builder → NSIS installer (Windows)
```

The installer is created in `frontend/dist/` as `KnowTwin Setup.exe`.

## Architecture

| Service | Port | Role |
|---------|------|------|
| `knowtwin-db` | 127.0.0.1:5436 | PostgreSQL 16 + pgvector + Apache AGE |
| `knowtwin-api` | 127.0.0.1:8090 | FastAPI — REST API + WebSocket |
| `knowtwin-ner` | internal | GLiNER entity extraction (CPU) |
| `knowtwin-tei` | internal | Jina-v4 embeddings (GPU, 11GB VRAM) |

The desktop app (Electron) runs locally via `npm run dev` — it connects to the API at localhost:8090.

## Demo dataset

The Juan Garcia demo simulates offboarding a senior developer:
- **8 source documents** (contracts, org charts, wikis, runbooks)
- **379 claims** with entity linking and graph materialization
- **203 graph edges** — Juan Garcia as central hub (degree 32)
- **7 contradictions** — auto-resolved (weak docs) + enterprise-disputed (strong docs)
- **4 interview sessions** with tacit knowledge
- **146 canonical predicates** across 18 knowledge clusters
- **83 entities** — people, systems, clients, projects, processes, risks

Money-shot query: *"Who really runs the ETL pipeline?"* → Andres Martin, with resolution provenance.

## API documentation

Interactive Swagger UI: http://localhost:8090/docs

Key endpoints:
- `POST /twin/query` — ask the digital twin
- `POST /projects/{id}/curator/run` — extract claims from documents
- `POST /interviews` — create interview sessions
- `GET /graph/all` — full knowledge graph
- `GET /api/v1/stats/*` — system metrics

## Without GPU

If no NVIDIA GPU is available, start without the embedding service:

```bash
docker compose up -d knowtwin-db knowtwin-ner knowtwin-api
```

Load the demo data dump (includes pre-computed embeddings):
```bash
docker exec knowtwin-db psql -U knowtwin -d knowtwin -f /seed/demo_data.sql
```

Twin queries and graph work with pre-embedded data. New document ingestion and interviews require TEI (GPU).

## License

PolyForm Noncommercial 1.0.0. Commercial use requires an Eco Consulting license.
