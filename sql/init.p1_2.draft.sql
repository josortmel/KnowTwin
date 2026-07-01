-- ============================================================================
-- KnowTwin — init.sql  P1.2 DRAFT (WIP — NOT MOUNTED, NOT APPLIED)
--
-- HARD CONSTRAINT (Hilo): draft only. Do NOT psql-apply or verify until P1.1 is
-- boot-verified AND the P1.1 report is code-reviewed. When P1.2 is greenlit, the
-- AS-IS CORE section below is lifted verbatim from EcoDB sql/init.sql and this
-- file REPLACES sql/init.sql (single CONSOLIDATED schema — no migration runner,
-- born at final version; EcoDB day-94 lesson).
--
-- Sources folded in: Spec §2.2 (claims) verbatim, §2.3/2.4/2.5/2.5.05 (new
-- tables), §2.5.2 (coverage view); governance.en.md §4 (RICH predicates_canonical
-- — NOT the Spec §2.5.1 4-col version, per Hilo). Cross-batch rulings folded.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 0. Extensions + AGE graph  (same bootstrap as P1.1 baseline)
-- ----------------------------------------------------------------------------
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
-- 1. AS-IS CORE (EcoDB) — TODO(P1.2 completion): lift verbatim from
--    EcoDB/sql/init.sql, ~33 tables, in FK-dependency order:
--      users, user_emails, organizations, workspaces, projects,
--      workspace_leads, project_leads, project_members,
--      agents, api_keys, nodes, triples, entity_dictionary,
--      documents, document_chunks, cell_runs, cell_task_configs,
--      cell_prompt_templates, llm_provider_keys, audit_log, trash,
--      + admin seed (users.id=1 name='admin' is_super) — REGRESSION GUARD
--        (test_auth + super_jwt depend on it).
--    ADAPTATIONS applied during the lift (see §3/§4 below): project_members
--    gets +role; triples gets +claim_id; bridge tables renamed; drops applied.
--    Preserve extensions + search_path (already set above).
-- ============================================================================
-- [PLACEHOLDER — AS-IS core DDL inserted here at P1.2 completion]


-- ============================================================================
-- 2. CLAIMS (replaces EcoDB `memories`) — Spec §2.2 verbatim
--    5 orthogonal typed state axes + CHECKs; embedding vector(512) NULLABLE.
--    Embed gate (P1.3) lives in claims.py::promote_claim — explicit IN-list,
--    NEVER >=. draft/rejected → embedding NULL; disputed IS embedded.
-- ============================================================================
CREATE TABLE claims (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id              INT REFERENCES users(id),
  agent_id             INT REFERENCES agents(id),
  project_id           INT NOT NULL REFERENCES projects(id),

  -- Claim content
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

  -- Five orthogonal state axes (typed columns, NOT JSONB)
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

  -- Operational metadata
  criticality          REAL NOT NULL DEFAULT 0.5 CHECK (criticality BETWEEN 0.0 AND 1.0),
  actionability        REAL DEFAULT NULL,
  sensitivity          TEXT NOT NULL DEFAULT 'restricted'
                         CHECK (sensitivity IN ('public', 'team', 'restricted')),

  -- Embedding (gated)
  embedding            vector(512),
  embedding_model      TEXT DEFAULT 'jina-v4',

  -- Dispute resolution data
  disputed_by_claim_id UUID REFERENCES claims(id),
  doc_strength         REAL,
  resolution_note      TEXT,
  resolved_by_user_id  INT REFERENCES users(id),

  -- Lifecycle
  tags                 TEXT[] NOT NULL DEFAULT '{}',
  created_at           TIMESTAMPTZ DEFAULT now(),
  updated_at           TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_claims_embedding ON claims
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 200);
CREATE INDEX idx_claims_project ON claims (project_id);
CREATE INDEX idx_claims_employee ON claims (employee_id);
CREATE INDEX idx_claims_corroboration ON claims (corroboration_level);
CREATE INDEX idx_claims_dispute ON claims (dispute_state);
CREATE INDEX idx_claims_subject ON claims (subject_entity);
CREATE INDEX idx_claims_predicate ON claims (predicate);
CREATE INDEX idx_claims_created ON claims (created_at DESC);
CREATE INDEX idx_claims_tags ON claims USING gin (tags);
CREATE INDEX idx_claims_content_trgm ON claims USING gin (evidence_text gin_trgm_ops);
CREATE INDEX idx_claims_disputed_by ON claims (disputed_by_claim_id)
  WHERE disputed_by_claim_id IS NOT NULL;

-- ============================================================================
-- 3. NEW domain tables — Spec §2.3 / §2.4 / §2.5 / §2.5.05
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

CREATE TABLE verifier_reports (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id      INT NOT NULL REFERENCES projects(id),
  run_type        TEXT NOT NULL CHECK (run_type IN ('pre_interview', 'post_session')),
  missed_entities JSONB DEFAULT '[]',
  misclassified_tiers JSONB DEFAULT '[]',
  undetected_contradictions JSONB DEFAULT '[]',
  structural_gaps JSONB DEFAULT '[]',
  status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'addressed', 'accepted')),
  created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE deletion_requests (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id      INT NOT NULL REFERENCES projects(id),
  claim_id        UUID NOT NULL REFERENCES claims(id),
  requested_by    INT NOT NULL REFERENCES users(id),
  reason          TEXT,
  status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
  reviewed_by     INT REFERENCES users(id),
  created_at      TIMESTAMPTZ DEFAULT now(),
  resolved_at     TIMESTAMPTZ
);

-- Bridge tables — renamed from EcoDB memory_entity_links / memory_document_links
-- (memory_id → claim_id). TODO(P1.2): lift EcoDB column set verbatim, rename FK.
-- CREATE TABLE claim_entity_links   ( claim_id UUID REFERENCES claims(id) ON DELETE CASCADE, ... );
-- CREATE TABLE claim_document_links ( claim_id UUID REFERENCES claims(id) ON DELETE CASCADE, ... );

-- ============================================================================
-- 4. PREDICATE GOVERNANCE — RICH DDL from governance.en.md §4 (Hilo ruling 5).
--    NOT the Spec §2.5.1 simple 4-col version. DROP predicate_embeddings (n/a here
--    — never created). SKIP pending_predicates.
-- ============================================================================
CREATE TABLE predicates_canonical (
  name            TEXT PRIMARY KEY,
  cluster         TEXT NOT NULL,
  ontology_layer  TEXT NOT NULL CHECK (ontology_layer IN ('core', 'domain')),
  domain          TEXT,
  description     TEXT,
  symmetric       BOOLEAN NOT NULL DEFAULT false,
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

CREATE INDEX idx_pc_cluster ON predicates_canonical (cluster);
CREATE INDEX idx_pc_state ON predicates_canonical (state);
CREATE INDEX idx_pc_embedding ON predicates_canonical
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 200);

CREATE TABLE predicate_aliases (
  alias       TEXT NOT NULL,
  canonical   TEXT NOT NULL REFERENCES predicates_canonical(name),
  domain      TEXT,
  auto_learned BOOLEAN DEFAULT false,
  confirmations INT DEFAULT 0,
  created_at  TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (alias, domain)
);
-- NOTE: predicate_aliases.domain is part of the PK and NULLable → PostgreSQL PK
-- forbids NULL. TODO(P1.2 verify): governance §4 declares PK(alias,domain) with a
-- nullable domain — must set domain NOT NULL DEFAULT '' OR use a UNIQUE index with
-- COALESCE. Flag to Hilo at P1.2 apply (potential §4 DDL bug).

-- ============================================================================
-- 5. Schema adaptations to AS-IS core (applied during the §1 lift)
-- ============================================================================
-- Cross-batch ruling: role model on project_members.
-- Implemented as TEXT + CHECK (EcoDB convention) rather than a CREATE TYPE ENUM —
-- functionally equivalent, migration-friendlier. (Ruling said "ENUM(...)".)
ALTER TABLE project_members
  ADD COLUMN role TEXT NOT NULL DEFAULT 'consumer'
  CHECK (role IN ('admin', 'curator', 'employee', 'consumer'));

-- Claim→triple linkage (hard-delete cascade). Reject path DELETEs triples by claim_id.
ALTER TABLE triples
  ADD COLUMN claim_id UUID REFERENCES claims(id) ON DELETE CASCADE;
CREATE INDEX idx_triples_claim_id ON triples (claim_id) WHERE claim_id IS NOT NULL;

-- ============================================================================
-- 6. Entity coverage VIEW — Spec §2.5.2 (criticality-weighted; numeric
--    correctness earned at P1.12, this file only needs it to COMPILE).
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
      THEN ROUND((COALESCE(cs.covered_criticality, 0)
                  / (COALESCE(ec.expected_count, 5) * COALESCE(ec.expected_criticality, 0.5))) * 100, 1)
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
-- 7. DROPs — EcoDB-specific, NOT ported (Hilo ruling 7).
--    (These tables are simply never created in the §1 lift; listed here as the
--    explicit exclusion set so the lift is auditable.)
--      claim_type_config (memory_type_config), agent_identity,
--      content_modality enum, multimodal tables, metacognition tables
--      (memory_clusters, foresights, cases, skills, tensions, ...),
--      predicate_embeddings.
-- ============================================================================

-- ============================================================================
-- 8. schema_version — KnowTwin P1.2 baseline
-- ============================================================================
INSERT INTO schema_version (version, notes)
VALUES ('0.2.0', 'KnowTwin P1.2: claims + interview_sessions + verified_documents + entity_expected_claims + verifier_reports + deletion_requests + rich predicate governance + entity_coverage view. memories→claims. Rich predicates_canonical from governance.en.md §4.');

-- NOTE: seed_predicates.py (10 offboarding + 10 reused EcoDB predicates) runs as a
-- POST-init script (Hilo ruling 8), not inline here.
