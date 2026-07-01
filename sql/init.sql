-- ============================================================================
-- KnowTwin — init.sql  v0.2.0 (P1.2 consolidated baseline)
--
-- SINGLE consolidated schema. Runs via docker-entrypoint-initdb.d on an EMPTY
-- volume only. There is NO migration runner (EcoDB day-94 fresh-install lesson):
-- this file must be a single consolidated schema, born at its final version.
--
-- Sources folded in:
--   EcoDB init.sql 5.0.0          (AS-IS core: users→audit_log→entity_dictionary)
--   migrate_5.0.1_to_5.1.0       (multi-tenant: org_id columns + propagation)
--   migrate_08_agents             (cognition_class)
--   migrate_5.2.0_to_5.3.0       (cell_prompt_templates, cell_task_configs, llm_provider_keys)
--   migrate_3_0h                  (name_canonical on nodes)
--   migrate_5.1.0_to_5.1.1       (graph_clusters)
--   Spec §2                      (claims, interview_sessions, verified_documents, etc.)
--   governance.en.md §4           (RICH predicates_canonical + aliases)
--   trigger_age_sync.sql          (knowtwin_graph AGE sync)
--
-- DROPPED from EcoDB (never created):
--   memories, memory_type ENUM, content_modality ENUM, memory_type_config,
--   memory_embeddings, agent_identity, memory_clusters, predicate_embeddings,
--   check_visibility(), ecodb_cell role + RLS + GRANTs.
-- ============================================================================

-- ============================================================================
-- §0  Extensions + AGE graph
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS age;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

ALTER DATABASE knowtwin SET search_path = public, ag_catalog, "$user";
ALTER DATABASE knowtwin SET session_preload_libraries = 'age';

LOAD 'age';
SET search_path = public, ag_catalog, "$user";

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'knowtwin_graph') THEN
    PERFORM create_graph('knowtwin_graph');
  END IF;
END$$;

-- ============================================================================
-- §1  Schema versioning
-- ============================================================================
CREATE TABLE schema_version (
  version    TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ DEFAULT now(),
  notes      TEXT
);

-- ============================================================================
-- §2  Enums
-- ============================================================================
CREATE TYPE visibility AS ENUM ('public', 'private');

-- ============================================================================
-- §3  Users + auth
-- ============================================================================
CREATE TABLE users (
  id         SERIAL PRIMARY KEY,
  name       TEXT NOT NULL,
  is_super   BOOLEAN NOT NULL DEFAULT false,
  is_ceo     BOOLEAN NOT NULL DEFAULT false,
  active     BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  CHECK (NOT (is_super AND is_ceo))
);

CREATE UNIQUE INDEX idx_users_one_super
  ON users (is_super) WHERE is_super = true;

CREATE TABLE user_emails (
  email      TEXT PRIMARY KEY,
  user_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  is_primary BOOLEAN NOT NULL DEFAULT false,
  added_at   TIMESTAMPTZ DEFAULT now()
);

CREATE UNIQUE INDEX idx_user_emails_one_primary
  ON user_emails (user_id) WHERE is_primary = true;
CREATE INDEX idx_user_emails_user_id ON user_emails (user_id);

CREATE TABLE organizations (
  id          SERIAL PRIMARY KEY,
  name        TEXT UNIQUE NOT NULL,
  ceo_user_id INT UNIQUE REFERENCES users(id),
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- Circular dep: users.organization_id → organizations. Added via ALTER.
ALTER TABLE users ADD COLUMN organization_id INT REFERENCES organizations(id) ON DELETE SET NULL;
CREATE INDEX idx_users_organization ON users (organization_id) WHERE organization_id IS NOT NULL;

CREATE TABLE agents (
  id              SERIAL PRIMARY KEY,
  identifier      TEXT UNIQUE NOT NULL,
  user_id         INT REFERENCES users(id),
  active          BOOLEAN DEFAULT true,
  last_seen       TIMESTAMPTZ,
  cognition_class VARCHAR(10) DEFAULT 'work'
                    CHECK (cognition_class IN ('narrative', 'work', 'mixed')),
  display_name    TEXT,
  description     TEXT,
  created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE api_keys (
  id                 SERIAL PRIMARY KEY,
  key_hash           TEXT UNIQUE NOT NULL,
  name               TEXT NOT NULL,
  user_id            INT REFERENCES users(id),
  expires_at         TIMESTAMPTZ,
  active             BOOLEAN DEFAULT true,
  replaced_by_key_id INT REFERENCES api_keys(id),
  grace_until        TIMESTAMPTZ,
  created_at         TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_api_keys_grace ON api_keys (grace_until)
  WHERE grace_until IS NOT NULL AND active = true;

-- ============================================================================
-- §4  Workspaces, projects, permissions
-- ============================================================================
CREATE TABLE workspaces (
  id              SERIAL PRIMARY KEY,
  organization_id INT REFERENCES organizations(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,
  created_at      TIMESTAMPTZ DEFAULT now(),
  UNIQUE (organization_id, name)
);

CREATE UNIQUE INDEX idx_workspaces_system_unique_name
  ON workspaces (name)
  WHERE organization_id IS NULL;

CREATE TABLE workspace_leads (
  workspace_id INT REFERENCES workspaces(id) ON DELETE CASCADE,
  user_id      INT REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE projects (
  id           SERIAL PRIMARY KEY,
  workspace_id INT REFERENCES workspaces(id) ON DELETE CASCADE,
  name         TEXT NOT NULL,
  is_common    BOOLEAN DEFAULT false,
  created_at   TIMESTAMPTZ DEFAULT now(),
  UNIQUE (workspace_id, name)
);

CREATE TABLE project_members (
  project_id INT REFERENCES projects(id) ON DELETE CASCADE,
  user_id    INT REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (project_id, user_id)
);

CREATE TABLE project_leads (
  project_id INT REFERENCES projects(id) ON DELETE CASCADE,
  user_id    INT REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (project_id, user_id)
);

CREATE INDEX idx_workspace_leads_user_id ON workspace_leads(user_id);
CREATE INDEX idx_project_leads_user_id   ON project_leads(user_id);

-- ============================================================================
-- §5  Teams (with organization_id from 5.1.0)
-- ============================================================================
CREATE TABLE teams (
  id              SERIAL PRIMARY KEY,
  name            TEXT UNIQUE NOT NULL,
  organization_id INT REFERENCES organizations(id) ON DELETE CASCADE,
  created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_teams_organization ON teams (organization_id);

CREATE TABLE team_members (
  team_id INT REFERENCES teams(id) ON DELETE CASCADE,
  user_id INT REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (team_id, user_id)
);

CREATE TABLE team_resources (
  team_id    INT REFERENCES teams(id) ON DELETE CASCADE,
  project_id INT REFERENCES projects(id) ON DELETE CASCADE,
  PRIMARY KEY (team_id, project_id)
);

-- ============================================================================
-- §6  Graph backbone — nodes + triples
-- ============================================================================
CREATE TABLE nodes (
  id             SERIAL PRIMARY KEY,
  name           TEXT UNIQUE NOT NULL,
  type           TEXT,
  description    TEXT,
  embedding      vector(512),
  name_canonical TEXT GENERATED ALWAYS AS (lower(name)) STORED,
  status         TEXT DEFAULT 'active'
                   CHECK (status IN ('active', 'merged')),
  merged_into    BIGINT REFERENCES nodes(id),
  created_at     TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE nodes ADD CONSTRAINT chk_no_self_merged_into
  CHECK (merged_into IS NULL OR merged_into != id);

CREATE UNIQUE INDEX idx_nodes_canonical    ON nodes (name_canonical);
CREATE INDEX idx_nodes_merged              ON nodes (merged_into) WHERE status = 'merged';
CREATE INDEX idx_nodes_name_trgm           ON nodes USING gin (name gin_trgm_ops);
CREATE INDEX idx_nodes_embedding           ON nodes
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 200);

CREATE TABLE triples (
  id          SERIAL PRIMARY KEY,
  subject_id  INT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  predicate   TEXT NOT NULL,
  object_id   INT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  author      TEXT,
  fecha       DATE,
  origen      TEXT,
  document_id UUID,
  metadata    JSONB DEFAULT '{}'
              CHECK (pg_column_size(metadata) < 65536),
  created_at  TIMESTAMPTZ DEFAULT now(),
  UNIQUE (subject_id, predicate, object_id)
);

CREATE INDEX idx_triples_subject       ON triples (subject_id);
CREATE INDEX idx_triples_object        ON triples (object_id);
CREATE INDEX idx_triples_predicate     ON triples (predicate);
CREATE INDEX idx_triples_fecha         ON triples (fecha)       WHERE fecha       IS NOT NULL;
CREATE INDEX idx_triples_origen        ON triples (origen)      WHERE origen      IS NOT NULL;
CREATE INDEX idx_triples_document_id   ON triples (document_id) WHERE document_id IS NOT NULL;

-- ============================================================================
-- §7  Claims (replaces EcoDB memories) — Spec §2.2
-- ============================================================================
CREATE TABLE claims (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id              INT REFERENCES users(id),
  agent_id             INT REFERENCES agents(id),
  project_id           INT NOT NULL REFERENCES projects(id),

  subject_entity       TEXT NOT NULL,
  predicate            TEXT NOT NULL,
  object_entity        TEXT,
  object_value         TEXT,
  evidence_text        TEXT NOT NULL,
  source_type          TEXT NOT NULL CHECK (source_type IN ('document', 'interview', 'curator')),
  source_id            UUID,
  source_date          TIMESTAMPTZ,
  employee_id          INT REFERENCES users(id),
  session_id           UUID,

  trust_tier           INT NOT NULL DEFAULT 0 CHECK (trust_tier BETWEEN 0 AND 2),
  confidence           REAL NOT NULL DEFAULT 0.5 CHECK (confidence BETWEEN 0.0 AND 1.0),
  corroboration_level  TEXT NOT NULL DEFAULT 'draft'
                         CHECK (corroboration_level IN (
                           'draft', 'single_source', 'corroborated',
                           'corroborated_by_employee', 'validated', 'rejected')),
  dispute_state        TEXT NOT NULL DEFAULT 'undisputed'
                         CHECK (dispute_state IN (
                           'undisputed', 'disputed', 'resolved_in_favor', 'resolved_against')),
  freshness_state      TEXT NOT NULL DEFAULT 'active'
                         CHECK (freshness_state IN ('active', 'stale', 'dormant')),

  criticality          REAL NOT NULL DEFAULT 0.5 CHECK (criticality BETWEEN 0.0 AND 1.0),
  actionability        REAL DEFAULT NULL,
  sensitivity          TEXT NOT NULL DEFAULT 'restricted'
                         CHECK (sensitivity IN ('public', 'team', 'restricted')),

  embedding            vector(512),
  embedding_model      TEXT DEFAULT 'jina-v4',

  -- NO ACTION on disputed_by FK is intentional — dispute evidence chain must
  -- be preserved. Resolve dispute (SET NULL) before deleting the disputing claim.
  disputed_by_claim_id UUID REFERENCES claims(id),
  doc_strength         REAL,
  resolution_note      TEXT,
  resolved_by_user_id  INT REFERENCES users(id),

  tags                 TEXT[] NOT NULL DEFAULT '{}',
  created_at           TIMESTAMPTZ DEFAULT now(),
  updated_at           TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_claims_embedding ON claims
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 200);
CREATE INDEX idx_claims_project        ON claims (project_id);
CREATE INDEX idx_claims_employee       ON claims (employee_id);
CREATE INDEX idx_claims_corroboration  ON claims (corroboration_level);
CREATE INDEX idx_claims_dispute        ON claims (dispute_state);
CREATE INDEX idx_claims_subject        ON claims (subject_entity);
CREATE INDEX idx_claims_predicate      ON claims (predicate);
CREATE INDEX idx_claims_created        ON claims (created_at DESC);
CREATE INDEX idx_claims_tags           ON claims USING gin (tags);
CREATE INDEX idx_claims_content_trgm   ON claims USING gin (evidence_text gin_trgm_ops);
CREATE INDEX idx_claims_disputed_by    ON claims (disputed_by_claim_id)
  WHERE disputed_by_claim_id IS NOT NULL;

-- ============================================================================
-- §8  Bridge tables (renamed from EcoDB memory_*_links → claim_*_links)
-- ============================================================================
CREATE TABLE claim_entity_links (
  claim_id       UUID REFERENCES claims(id) ON DELETE CASCADE,
  entity_node_id BIGINT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  link_type      TEXT DEFAULT 'mentions',
  auto           BOOLEAN DEFAULT true,
  created_at     TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (claim_id, entity_node_id)
);

CREATE INDEX idx_cel_entity ON claim_entity_links (entity_node_id);

CREATE TABLE claim_document_links (
  claim_id    UUID REFERENCES claims(id) ON DELETE CASCADE,
  document_id UUID,
  link_type   TEXT DEFAULT 'source',
  confidence  REAL,
  validated   BOOLEAN DEFAULT false,
  PRIMARY KEY (claim_id, document_id)
);

ALTER TABLE claim_document_links ADD CONSTRAINT chk_cdl_confidence_range
  CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1);

-- ============================================================================
-- §9  Documents
-- ============================================================================
CREATE TABLE documents (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id  INT REFERENCES workspaces(id) NOT NULL,
  project_id    INT REFERENCES projects(id) NOT NULL,
  visibility    visibility NOT NULL DEFAULT 'public',
  uri           TEXT NOT NULL UNIQUE,
  filename      TEXT NOT NULL,
  doc_type      TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued','processing','indexed','failed','deleted')),
  file_hash     TEXT,
  retry_count   INT NOT NULL DEFAULT 0,
  processing_started_at TIMESTAMPTZ,
  processing_metrics    JSONB,
  base_weight   REAL NOT NULL DEFAULT 0.7,
  trust_origin  TEXT DEFAULT 'manual',
  trust_tier    INT DEFAULT 1 CHECK(trust_tier BETWEEN 0 AND 2),
  content_fingerprint TEXT,
  document_version INT DEFAULT 1,
  supersedes_document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
  reconciled    BOOLEAN DEFAULT false,
  last_indexed  TIMESTAMPTZ,
  last_modified TIMESTAMPTZ,
  trust_hint    TEXT DEFAULT NULL
                  CHECK (trust_hint IN ('formal_contract','adr','signed_plan','wiki','presentation','email','orgchart','other')),
  metadata      JSONB DEFAULT '{}',
  created_at    TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE documents ADD CONSTRAINT chk_no_self_supersede
  CHECK (supersedes_document_id IS NULL OR supersedes_document_id != id);
ALTER TABLE documents ADD CONSTRAINT chk_fingerprint_len
  CHECK (content_fingerprint IS NULL OR length(content_fingerprint) = 64);

CREATE INDEX idx_documents_uri        ON documents (uri);
CREATE INDEX idx_documents_workspace  ON documents (workspace_id);
CREATE INDEX idx_documents_project    ON documents (project_id);

CREATE TABLE document_chunks (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index INT NOT NULL,
  content     TEXT NOT NULL,
  embedding   vector(512),
  section_path TEXT,
  metadata    JSONB DEFAULT '{}',
  tags        TEXT[] DEFAULT '{}',
  UNIQUE (document_id, chunk_index)
);

CREATE INDEX idx_doc_chunks_embedding ON document_chunks
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 200);
CREATE INDEX idx_dc_fulltext ON document_chunks
  USING gin (to_tsvector('spanish', content));
CREATE INDEX idx_dc_document_id ON document_chunks (document_id);

-- FK triples.document_id → documents(id). Defined via ALTER because triples is
-- created before documents (FK ordering).
ALTER TABLE triples
  ADD CONSTRAINT fk_triples_document_id
  FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL;

-- FK claim_document_links.document_id → documents(id). Added after documents exists.
ALTER TABLE claim_document_links
  ADD CONSTRAINT fk_cdl_document_id
  FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE;

CREATE INDEX idx_cdl_document ON claim_document_links (document_id);

CREATE TABLE document_entity_links (
  document_id    UUID REFERENCES documents(id) ON DELETE CASCADE,
  entity_node_id BIGINT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  chunk_id       UUID NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
  created_at     TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (document_id, entity_node_id, chunk_id)
);

CREATE INDEX idx_del_entity ON document_entity_links (entity_node_id);

-- ============================================================================
-- §10  Entity management
-- ============================================================================
CREATE TABLE stop_entities (
  id              SERIAL PRIMARY KEY,
  name            TEXT NOT NULL,
  name_normalized TEXT NOT NULL,
  reason          TEXT,
  created_by      INT NOT NULL REFERENCES users(id),
  created_at      TIMESTAMPTZ DEFAULT now(),
  UNIQUE (name_normalized)
);

CREATE TABLE entity_alias_candidates (
  id SERIAL PRIMARY KEY,
  source_name TEXT NOT NULL,
  target_node_id BIGINT NOT NULL REFERENCES nodes(id),
  confidence REAL NOT NULL,
  occurrences INT DEFAULT 1,
  sample_contexts TEXT[],
  status TEXT DEFAULT 'pending'
    CHECK (status IN ('pending', 'approved', 'rejected', 'archived')),
  first_seen TIMESTAMPTZ DEFAULT now(),
  last_seen TIMESTAMPTZ DEFAULT now(),
  reviewed_by INT REFERENCES users(id)
);

CREATE INDEX idx_eac_source_name ON entity_alias_candidates (source_name);
CREATE INDEX idx_eac_target_node ON entity_alias_candidates (target_node_id);
CREATE INDEX idx_eac_pending ON entity_alias_candidates (status) WHERE status = 'pending';
ALTER TABLE entity_alias_candidates ADD CONSTRAINT chk_confidence_range
  CHECK (confidence BETWEEN 0 AND 1);
ALTER TABLE entity_alias_candidates ADD CONSTRAINT chk_sample_contexts_len
  CHECK (sample_contexts IS NULL OR array_length(sample_contexts, 1) <= 20);

CREATE TABLE entity_merge_log (
  id SERIAL PRIMARY KEY,
  source_node_id BIGINT NOT NULL,
  target_node_id BIGINT NOT NULL,
  target_original_id BIGINT NOT NULL,
  merged_by INT REFERENCES users(id),
  reason TEXT,
  merged_at TIMESTAMPTZ DEFAULT now(),
  undone_at TIMESTAMPTZ
);

CREATE INDEX idx_eml_source ON entity_merge_log (source_node_id);
CREATE INDEX idx_eml_target ON entity_merge_log (target_node_id);
ALTER TABLE entity_merge_log ADD CONSTRAINT chk_no_self_merge
  CHECK (source_node_id != target_node_id);

CREATE TABLE related_documents (
  source_id UUID REFERENCES documents(id) ON DELETE CASCADE,
  target_id UUID REFERENCES documents(id) ON DELETE CASCADE,
  relation_type TEXT
    CHECK (relation_type IN ('duplicate', 'near_duplicate', 'revision_of', 'supersedes', 'derived_from')),
  similarity REAL,
  detected_at TIMESTAMPTZ DEFAULT now(),
  confirmed_by INT REFERENCES users(id),
  PRIMARY KEY (source_id, target_id)
);

CREATE INDEX idx_related_target ON related_documents (target_id);
ALTER TABLE related_documents ADD CONSTRAINT chk_no_self_relation
  CHECK (source_id != target_id);
ALTER TABLE related_documents ADD CONSTRAINT chk_similarity_range
  CHECK (similarity IS NULL OR similarity BETWEEN 0 AND 1);

-- ============================================================================
-- §11  Operational tables
-- ============================================================================
CREATE TABLE search_log (
  id            BIGSERIAL PRIMARY KEY,
  user_id       INT REFERENCES users(id),
  agent_id      INT REFERENCES agents(id),
  query_text    TEXT NOT NULL,
  query_type    TEXT,
  results_count INT NOT NULL DEFAULT 0,
  latency_ms    INT NOT NULL,
  failed        BOOLEAN DEFAULT false,
  project_ids   INT[],
  created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_search_log_created ON search_log (created_at DESC);

CREATE TABLE user_preferences (
  user_id    INT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  prefs      JSONB NOT NULL DEFAULT '{}',
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE trash (
  id              UUID PRIMARY KEY,
  original_table  TEXT NOT NULL,
  original_data   JSONB NOT NULL,
  deleted_by      INT REFERENCES users(id),
  deleted_at      TIMESTAMPTZ DEFAULT now(),
  retention_until TIMESTAMPTZ DEFAULT (now() + INTERVAL '90 days')
);

CREATE INDEX idx_trash_retention ON trash (retention_until);

CREATE TABLE audit_log (
  id              BIGSERIAL PRIMARY KEY,
  user_id         INT REFERENCES users(id),
  agent_id        INT REFERENCES agents(id),
  organization_id INT,
  action          TEXT NOT NULL,
  resource        TEXT NOT NULL,
  resource_id     TEXT,
  details         JSONB DEFAULT '{}',
  ip_address      INET,
  created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_audit_user              ON audit_log (user_id);
CREATE INDEX idx_audit_created           ON audit_log (created_at DESC);
CREATE INDEX idx_audit_resource          ON audit_log (resource, resource_id);
CREATE INDEX idx_audit_log_organization  ON audit_log (organization_id) WHERE organization_id IS NOT NULL;

-- ============================================================================
-- §12  Entity dictionary
-- ============================================================================
CREATE TABLE entity_dictionary (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  name_normalized TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  notes TEXT,
  created_by INT REFERENCES users(id),
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(name_normalized)
);

CREATE INDEX idx_ed_name ON entity_dictionary (name_normalized);

INSERT INTO entity_dictionary (name, name_normalized, entity_type) VALUES
  ('PostgreSQL',     'postgresql',      'tecnologia'),
  ('Docker',         'docker',          'tecnologia'),
  ('FastAPI',        'fastapi',         'producto'),
  ('Jina v4',        'jina v4',         'producto'),
  ('GLiNER',         'gliner',          'producto'),
  ('KnowTwin',       'knowtwin',        'proyecto');

-- ============================================================================
-- §13  Telemetry + search support
-- ============================================================================
CREATE TABLE injection_telemetry (
  id SERIAL PRIMARY KEY,
  injection_id TEXT NOT NULL UNIQUE,
  memory_ids UUID[] NOT NULL,
  scores REAL[],
  agent_identifier TEXT,
  session_id TEXT,
  prompt_hash TEXT,
  status TEXT DEFAULT 'injected' CHECK (status IN ('injected', 'used', 'ignored')),
  use_score REAL,
  novel_entities TEXT[],
  created_at TIMESTAMPTZ DEFAULT now(),
  evaluated_at TIMESTAMPTZ
);

CREATE INDEX idx_it_status  ON injection_telemetry (status);
CREATE INDEX idx_it_created ON injection_telemetry (created_at DESC);

CREATE TABLE corpus_vocabulary (
  term TEXT PRIMARY KEY,
  embedding vector(512),
  doc_freq INT DEFAULT 1,
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_cv_embedding ON corpus_vocabulary
  USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=200);

-- ============================================================================
-- §14  Graph clusters (Louvain community detection)
-- ============================================================================
CREATE TABLE graph_clusters (
  node_id     INT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  cluster_id  INT NOT NULL,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (node_id)
);

CREATE INDEX idx_graph_clusters_cluster ON graph_clusters (cluster_id);

-- ============================================================================
-- §15  Cell infrastructure (tables only — role/RLS/GRANTs deferred to P1.9)
-- ============================================================================
CREATE TABLE cell_runs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  cell_type       TEXT NOT NULL,
  agent_id        INT REFERENCES agents(id),
  model           TEXT NOT NULL,
  prompt_version  TEXT,
  started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at     TIMESTAMPTZ,
  status          TEXT DEFAULT 'running'
                  CHECK (status IN ('running','completed','failed')),
  tokens_used     INT CHECK (tokens_used IS NULL OR tokens_used >= 0),
  cost_usd        REAL CHECK (cost_usd IS NULL OR cost_usd >= 0),
  items_created   INT DEFAULT 0 CHECK (items_created >= 0),
  errors          JSONB DEFAULT '[]'
                  CHECK (pg_column_size(errors) < 65536),
  metrics         JSONB NOT NULL DEFAULT '{}'
                  CHECK (pg_column_size(metrics) < 65536),
  created_at      TIMESTAMPTZ DEFAULT now(),
  CHECK (finished_at IS NULL OR finished_at >= started_at)
);

CREATE INDEX idx_cr_cell_type       ON cell_runs (cell_type, started_at DESC);
CREATE INDEX idx_cr_agent           ON cell_runs (agent_id) WHERE agent_id IS NOT NULL;
CREATE INDEX idx_cr_idempotency     ON cell_runs (agent_id, cell_type, status);
CREATE INDEX idx_cr_metrics_period  ON cell_runs ((metrics->>'period_start'), (metrics->>'period_end'))
  WHERE status IN ('completed', 'running');

CREATE TABLE cell_prompt_templates (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  cell_type TEXT NOT NULL,
  content TEXT NOT NULL CHECK (char_length(content) <= 32000),
  is_default BOOLEAN NOT NULL DEFAULT false,
  created_by INTEGER REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(name)
);

CREATE UNIQUE INDEX idx_cell_prompt_templates_default
  ON cell_prompt_templates(cell_type) WHERE is_default = true;

CREATE TABLE cell_task_configs (
  id SERIAL PRIMARY KEY,
  agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  cell_type TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT true,
  model TEXT NOT NULL DEFAULT 'deepseek-chat',
  provider TEXT NOT NULL DEFAULT 'deepseek',
  prompt_template_id INTEGER REFERENCES cell_prompt_templates(id),
  schedule_cron TEXT,
  level TEXT CHECK (level IS NULL OR level IN ('weekly','monthly','quarterly','yearly')),
  config JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(agent_id, cell_type, level)
);

CREATE INDEX idx_cell_task_configs_agent
  ON cell_task_configs(agent_id);
CREATE INDEX idx_cell_task_configs_enabled
  ON cell_task_configs(agent_id, enabled) WHERE enabled = true;
CREATE UNIQUE INDEX idx_cell_task_configs_null_level
  ON cell_task_configs(agent_id, cell_type) WHERE level IS NULL;

CREATE TABLE llm_provider_keys (
  id SERIAL PRIMARY KEY,
  provider TEXT NOT NULL,
  api_key_encrypted TEXT NOT NULL,
  model_default TEXT,
  display_name TEXT,
  added_by INTEGER REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(provider)
);

-- ============================================================================
-- §16  KnowTwin domain tables — Spec §2.3 / §2.4 / §2.5 / §2.5.05
-- ============================================================================
CREATE TABLE interview_sessions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id      INT NOT NULL REFERENCES projects(id),
  employee_id     INT NOT NULL REFERENCES users(id),
  topic           TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'scheduled'
                    CHECK (status IN ('scheduled', 'in_progress', 'completed', 'cancelled')),
  planned_duration_min INT DEFAULT 45,
  actual_duration_min  INT,
  claims_extracted INT DEFAULT 0,
  coverage_before  REAL,
  coverage_after   REAL,
  dossier          JSONB,
  rollup           TEXT,
  created_at       TIMESTAMPTZ DEFAULT now(),
  completed_at     TIMESTAMPTZ
);

-- FK claims.session_id → interview_sessions(id). Added via ALTER (FK ordering).
ALTER TABLE claims
  ADD CONSTRAINT fk_claims_session
  FOREIGN KEY (session_id) REFERENCES interview_sessions(id) ON DELETE SET NULL;
CREATE INDEX idx_claims_session ON claims (session_id);

CREATE TABLE verified_documents (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id      INT NOT NULL REFERENCES projects(id),
  domain_area     TEXT NOT NULL,
  content_md      TEXT NOT NULL,
  version         INT NOT NULL DEFAULT 1,
  status          TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'verified', 'finalized')),
  gap_count       INT DEFAULT 0,
  contradiction_count INT DEFAULT 0,
  created_at      TIMESTAMPTZ DEFAULT now(),
  updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE entity_expected_claims (
  id              SERIAL PRIMARY KEY,
  project_id      INT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  entity_name     TEXT NOT NULL,
  entity_type     TEXT NOT NULL,
  expected_count  INT NOT NULL DEFAULT 5,
  expected_criticality REAL NOT NULL DEFAULT 0.5,
  created_by      TEXT DEFAULT 'curator',
  created_at      TIMESTAMPTZ DEFAULT now(),
  UNIQUE (project_id, entity_name)
);

CREATE TABLE org_settings (
  project_id  INT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  config      JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE verifier_reports (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id      INT NOT NULL REFERENCES projects(id),
  run_type        TEXT NOT NULL CHECK (run_type IN ('pre_interview', 'post_session')),
  missed_entities JSONB DEFAULT '[]',
  misclassified_tiers JSONB DEFAULT '[]',
  undetected_contradictions JSONB DEFAULT '[]',
  structural_gaps JSONB DEFAULT '[]',
  status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'addressed', 'accepted')),
  created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE deletion_requests (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id      INT NOT NULL REFERENCES projects(id),
  claim_id        UUID NOT NULL REFERENCES claims(id),
  requested_by    INT NOT NULL REFERENCES users(id),
  reason          TEXT,
  status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
  reviewed_by     INT REFERENCES users(id),
  created_at      TIMESTAMPTZ DEFAULT now(),
  resolved_at     TIMESTAMPTZ
);

-- ============================================================================
-- §17  Predicate governance — RICH DDL from governance.en.md §4
-- ============================================================================
CREATE TABLE predicates_canonical (
  name            TEXT PRIMARY KEY,
  cluster         TEXT NOT NULL,
  ontology_layer  TEXT NOT NULL CHECK (ontology_layer IN ('core', 'domain')),
  domain          TEXT,
  description     TEXT,
  "symmetric"     BOOLEAN NOT NULL DEFAULT false,
  inverse_of      TEXT REFERENCES predicates_canonical(name) DEFERRABLE INITIALLY DEFERRED,
  transitive      BOOLEAN NOT NULL DEFAULT false,
  domain_types    TEXT[] NOT NULL DEFAULT '{}',
  range_types     TEXT[] NOT NULL DEFAULT '{}',
  authority_agents TEXT[] NOT NULL DEFAULT '{}',
  state           TEXT NOT NULL DEFAULT 'approved'
                  CHECK (state IN ('experimental','candidate','approved','deprecated','archived','forbidden')),
  deprecated_since TIMESTAMPTZ,
  replaced_by     TEXT REFERENCES predicates_canonical(name),
  embedding          vector(512),
  embedding_model    TEXT DEFAULT 'jina-v4',
  embedding_version  TEXT,
  embedding_updated  TIMESTAMPTZ,
  created_at         TIMESTAMPTZ DEFAULT now(),
  updated_at         TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_pc_cluster   ON predicates_canonical (cluster);
CREATE INDEX idx_pc_state     ON predicates_canonical (state);
CREATE INDEX idx_pc_embedding ON predicates_canonical
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 200);

CREATE TABLE predicate_aliases (
  alias       TEXT NOT NULL,
  canonical   TEXT NOT NULL REFERENCES predicates_canonical(name),
  domain      TEXT NOT NULL DEFAULT '',
  auto_learned BOOLEAN DEFAULT false,
  confirmations INT DEFAULT 0,
  created_at  TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (alias, domain)
);

-- ============================================================================
-- §18  Schema adaptations to AS-IS core
-- ============================================================================
ALTER TABLE project_members
  ADD COLUMN role TEXT NOT NULL DEFAULT 'consumer'
  CHECK (role IN ('admin', 'curator', 'employee', 'consumer'));

ALTER TABLE triples
  ADD COLUMN claim_id UUID REFERENCES claims(id) ON DELETE CASCADE;
CREATE INDEX idx_triples_claim_id ON triples (claim_id) WHERE claim_id IS NOT NULL;

-- ============================================================================
-- §19  Entity coverage view — Spec §2.5.2
-- ============================================================================
CREATE VIEW entity_coverage AS
WITH claim_stats AS (
  SELECT
    c.subject_entity,
    c.project_id,
    COUNT(DISTINCT c.id) FILTER (
      WHERE c.corroboration_level IN ('single_source', 'corroborated',
            'corroborated_by_employee', 'validated')
    ) AS confirmed_count,
    SUM(c.criticality) FILTER (
      WHERE c.corroboration_level IN ('single_source', 'corroborated',
            'corroborated_by_employee', 'validated')
    ) AS covered_criticality,
    bool_or(c.dispute_state = 'disputed') AS has_dispute,
    bool_or(c.corroboration_level = 'validated') AS has_validated,
    bool_or(c.freshness_state = 'stale') AS has_stale,
    bool_or(c.freshness_state = 'active') AS has_active
  FROM claims c
  GROUP BY c.subject_entity, c.project_id
),
coverage_base AS (
  SELECT
    ec.project_id,
    n.name AS entity_name,
    n.type AS entity_type,
    COALESCE(cs.confirmed_count, 0) AS confirmed_count,
    COALESCE(ec.expected_count, 5) AS expected_count,
    COALESCE(cs.covered_criticality, 0) AS covered_criticality,
    COALESCE(ec.expected_criticality, 0.5) AS expected_criticality,
    CASE WHEN (COALESCE(ec.expected_count, 5) * COALESCE(ec.expected_criticality, 0.5)) > 0
      THEN ROUND(((COALESCE(cs.covered_criticality, 0)
                  / (COALESCE(ec.expected_count, 5) * COALESCE(ec.expected_criticality, 0.5))) * 100)::numeric, 1)
      ELSE 0
    END AS coverage_pct,
    COALESCE(cs.has_dispute, false) AS has_dispute,
    COALESCE(cs.has_validated, false) AS has_validated,
    COALESCE(cs.has_stale, false) AS has_stale,
    COALESCE(cs.has_active, false) AS has_active,
    COALESCE(cs.confirmed_count, 0) AS cc
  FROM entity_expected_claims ec
  JOIN nodes n ON n.name = ec.entity_name
  LEFT JOIN claim_stats cs ON cs.subject_entity = n.name AND cs.project_id = ec.project_id
)
SELECT
  project_id, entity_name, entity_type,
  confirmed_count, expected_count, covered_criticality, expected_criticality,
  coverage_pct,
  CASE
    WHEN cc = 0 THEN 'unknown'
    WHEN has_stale AND NOT has_active THEN 'stale'
    WHEN has_dispute THEN 'disputed'
    WHEN has_validated THEN 'validated'
    WHEN coverage_pct >= 50.0 THEN 'clear'
    WHEN cc > 0 THEN 'partial'
    ELSE 'unknown'
  END AS coverage_state
FROM coverage_base;

-- ============================================================================
-- §20  Triggers — organization propagation (from 5.1.0)
-- ============================================================================
CREATE OR REPLACE FUNCTION propagate_user_org_id() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
DECLARE
  target_user_id INT;
  resolved_org_id INT;
BEGIN
  target_user_id := COALESCE(NEW.user_id, OLD.user_id);

  SELECT DISTINCT w.organization_id INTO resolved_org_id
  FROM workspace_leads wl
  JOIN workspaces w ON w.id = wl.workspace_id
  WHERE wl.user_id = target_user_id AND w.organization_id IS NOT NULL
  LIMIT 1;

  IF resolved_org_id IS NULL THEN
    SELECT DISTINCT w.organization_id INTO resolved_org_id
    FROM project_members pm
    JOIN projects p ON p.id = pm.project_id
    JOIN workspaces w ON w.id = p.workspace_id
    WHERE pm.user_id = target_user_id AND w.organization_id IS NOT NULL
    LIMIT 1;
  END IF;

  UPDATE users SET organization_id = resolved_org_id WHERE id = target_user_id;
  RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE TRIGGER trg_propagate_org_ws_leads
  AFTER INSERT OR UPDATE OR DELETE ON workspace_leads
  FOR EACH ROW EXECUTE FUNCTION propagate_user_org_id();

CREATE TRIGGER trg_propagate_org_proj_members
  AFTER INSERT OR UPDATE OR DELETE ON project_members
  FOR EACH ROW EXECUTE FUNCTION propagate_user_org_id();

-- ============================================================================
-- §21  Triggers — team cross-org constraint (from 5.1.0)
-- ============================================================================
CREATE OR REPLACE FUNCTION check_team_org_consistency() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
DECLARE
  team_org INT;
  member_org INT;
  resource_org INT;
BEGIN
  SELECT organization_id INTO team_org FROM teams WHERE id = NEW.team_id;

  IF TG_TABLE_NAME = 'team_members' THEN
    SELECT organization_id INTO member_org FROM users WHERE id = NEW.user_id;
    IF team_org IS NOT NULL AND member_org IS NOT NULL AND team_org != member_org THEN
      RAISE EXCEPTION 'Cannot add user from org % to team of org %', member_org, team_org;
    END IF;
  ELSIF TG_TABLE_NAME = 'team_resources' THEN
    SELECT w.organization_id INTO resource_org
    FROM projects p JOIN workspaces w ON w.id = p.workspace_id
    WHERE p.id = NEW.project_id;
    IF team_org IS NOT NULL AND resource_org IS NOT NULL AND team_org != resource_org THEN
      RAISE EXCEPTION 'Cannot add project from org % to team of org %', resource_org, team_org;
    END IF;
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_check_team_member_org
  BEFORE INSERT OR UPDATE ON team_members
  FOR EACH ROW EXECUTE FUNCTION check_team_org_consistency();

CREATE TRIGGER trg_check_team_resource_org
  BEFORE INSERT OR UPDATE ON team_resources
  FOR EACH ROW EXECUTE FUNCTION check_team_org_consistency();

-- ============================================================================
-- §22  Triggers — AGE graph sync (knowtwin_graph)
-- ============================================================================
-- AGE 1.5.0 does NOT support parameterized Cypher ($1::agtype) from PL/pgSQL.
-- Names are escaped via cypher_quote() → Cypher-safe single-quoted literals.

CREATE OR REPLACE FUNCTION cypher_quote(val text) RETURNS text AS $fn$
    SELECT chr(39)
        || replace(replace(val, chr(92), chr(92)||chr(92)), chr(39), chr(92)||chr(39))
        || chr(39)
$fn$ LANGUAGE sql IMMUTABLE STRICT;

CREATE OR REPLACE FUNCTION age_sync_insert() RETURNS trigger AS
$body$
BEGIN
    EXECUTE format(
        'SELECT * FROM cypher(''knowtwin_graph'', $cq$CREATE (n:Entity {name: %s, sql_id: %s}) RETURN id(n)$cq$) AS (node_id agtype)',
        cypher_quote(NEW.name), NEW.id
    );
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'AGE sync INSERT failed for node %: %', NEW.id, SQLERRM;
    RETURN NEW;
END;
$body$
LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION age_sync_remove() RETURNS trigger AS
$body$
DECLARE
    target_id int;
BEGIN
    IF TG_OP = 'DELETE' THEN
        target_id := OLD.id;
    ELSE
        target_id := NEW.id;
    END IF;
    IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND NEW.status != 'active' AND (OLD.status = 'active' OR OLD.status IS NULL)) THEN
        EXECUTE format(
            'SELECT * FROM cypher(''knowtwin_graph'', $cq$MATCH (n:Entity {sql_id: %s}) DETACH DELETE n$cq$) AS (d agtype)',
            target_id
        );
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'AGE sync REMOVE failed for node %: %', COALESCE(target_id, -1), SQLERRM;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$body$
LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION age_sync_rename() RETURNS trigger AS
$body$
BEGIN
    IF NEW.name != OLD.name THEN
        EXECUTE format(
            'SELECT * FROM cypher(''knowtwin_graph'', $cq$MATCH (n:Entity {sql_id: %s}) SET n.name = %s RETURN id(n)$cq$) AS (node_id agtype)',
            NEW.id, cypher_quote(NEW.name)
        );
    END IF;
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'AGE sync RENAME failed for node %: %', NEW.id, SQLERRM;
    RETURN NEW;
END;
$body$
LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION age_sync_reactivate() RETURNS trigger AS
$body$
BEGIN
    IF NEW.status = 'active' AND (OLD.status != 'active' OR OLD.status IS NULL) THEN
        EXECUTE format(
            'SELECT * FROM cypher(''knowtwin_graph'', $cq$CREATE (n:Entity {name: %s, sql_id: %s}) RETURN id(n)$cq$) AS (node_id agtype)',
            cypher_quote(NEW.name), NEW.id
        );
    END IF;
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'AGE sync REACTIVATE failed for node %: %', NEW.id, SQLERRM;
    RETURN NEW;
END;
$body$
LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_age_sync_insert ON nodes;
CREATE TRIGGER trg_age_sync_insert
    AFTER INSERT ON nodes
    FOR EACH ROW
    WHEN (NEW.status = 'active' OR NEW.status IS NULL)
    EXECUTE FUNCTION age_sync_insert();

DROP TRIGGER IF EXISTS trg_age_sync_remove ON nodes;
CREATE TRIGGER trg_age_sync_remove
    AFTER DELETE OR UPDATE OF status ON nodes
    FOR EACH ROW
    EXECUTE FUNCTION age_sync_remove();

DROP TRIGGER IF EXISTS trg_age_sync_rename ON nodes;
CREATE TRIGGER trg_age_sync_rename
    AFTER UPDATE OF name ON nodes
    FOR EACH ROW
    WHEN (NEW.status = 'active')
    EXECUTE FUNCTION age_sync_rename();

DROP TRIGGER IF EXISTS trg_age_sync_reactivate ON nodes;
CREATE TRIGGER trg_age_sync_reactivate
    AFTER UPDATE OF status ON nodes
    FOR EACH ROW
    WHEN (NEW.status = 'active')
    EXECUTE FUNCTION age_sync_reactivate();

-- ============================================================================
-- §23  Seed data — admin bootstrap (REGRESSION GUARD: test_auth + super_jwt)
-- ============================================================================
INSERT INTO users (name, is_super, is_ceo) VALUES ('admin', true, false);
INSERT INTO user_emails (email, user_id, is_primary) VALUES ('admin@example.com', 1, true);

INSERT INTO workspaces (name) VALUES ('default');
INSERT INTO projects (workspace_id, name, is_common) VALUES (1, 'general', true);
INSERT INTO project_members (project_id, user_id) VALUES (1, 1);

INSERT INTO agents (identifier, user_id) VALUES
  ('default', 1), ('SIN_AUTOR', 1);

-- ============================================================================
-- §24  Schema version
-- ============================================================================
INSERT INTO schema_version (version, notes)
VALUES ('0.2.0', 'KnowTwin P1.2: AS-IS core (33 tables from EcoDB 5.0.0+5.1.0+5.3.0) + claims (replaces memories) + interview_sessions + verified_documents + entity_expected_claims + verifier_reports + deletion_requests + rich predicate governance (governance.en.md §4) + entity_coverage view + AGE sync triggers (knowtwin_graph). Dropped: memories, memory_type, content_modality, memory_type_config, agent_identity, memory_clusters, memory_embeddings, predicate_embeddings, check_visibility.');
