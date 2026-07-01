-- ============================================================================
-- KnowTwin — init.sql (P1.1 MINIMAL consolidated baseline)
--
-- Runs automatically via docker-entrypoint-initdb.d against the `knowtwin`
-- database (created by POSTGRES_DB) on an EMPTY volume only. There is NO
-- migration runner (EcoDB day-94 fresh-install lesson): this file must be a
-- single CONSOLIDATED schema, born at its final version. Do NOT split into a
-- frozen baseline + manual migrations.
--
-- SCOPE — P1.1 mounts ONLY the bootstrap layer so the DB boots healthy:
--   extensions (pgvector, AGE, pg_trgm) + persisted search_path + AGE graph
--   + schema_version. The REAL domain schema (claims, interview_sessions,
--   verified_documents, predicates_canonical, …) is folded in at P1.2.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Extensions + AGE graph initialization
-- ----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS vector;       -- pgvector >= 0.9
CREATE EXTENSION IF NOT EXISTS age;          -- Apache AGE 1.5.0 para PG16
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- trigram fuzzy matching

-- AGE must be preloaded per session and ag_catalog on the search_path. Persist
-- at the DATABASE level so EVERY connection inherits it. public FIRST so CREATE
-- TABLE (this file + P1.2) lands in public, not ag_catalog.
ALTER DATABASE knowtwin SET search_path = public, ag_catalog, "$user";
ALTER DATABASE knowtwin SET session_preload_libraries = 'age';

LOAD 'age';
SET search_path = public, ag_catalog, "$user";

-- Main system graph. Idempotent.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'knowtwin_graph') THEN
    PERFORM create_graph('knowtwin_graph');
  END IF;
END$$;

-- ----------------------------------------------------------------------------
-- Schema versioning
-- ----------------------------------------------------------------------------
CREATE TABLE schema_version (
  version    TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ DEFAULT now(),
  notes      TEXT
);

INSERT INTO schema_version (version, notes)
VALUES ('0.1.0', 'KnowTwin P1.1 baseline: extensions (pgvector/AGE/pg_trgm) + search_path + knowtwin_graph. Domain schema folded in at P1.2.');
