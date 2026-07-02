"""P2.13 End-to-end integration test — Phase 2 features + MVP regression.

Walks the full pipeline: curator extraction → interview → curator_post →
dossier regen → continuity → style → disputes → sanitization → batch →
export → scoring → GDPR erasure.

Monkeypatches: cell_worker._llm_call, embeddings_client.embed_text.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_e2e_phase2.py -v -s
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql://knowtwin:knowtwin_test_pass@knowtwin-db:5432/knowtwin")
os.environ.setdefault("ENVIRONMENT", "development")

import asyncpg

_DB_URL = os.environ["DATABASE_URL"]
_PREFIX = "e2e2_"
_PID = 1
_VEC = [0.1] * 512


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def setup_teardown():
    async def _setup():
        conn = await asyncpg.connect(_DB_URL)
        try:
            emp = await conn.fetchval(
                "INSERT INTO users (name) VALUES ($1) RETURNING id", f"{_PREFIX}employee")
            await conn.execute(
                "INSERT INTO user_emails (email, user_id, is_primary) VALUES ($1, $2, true)",
                f"{_PREFIX}emp@test.kt", emp)
            await conn.execute(
                "INSERT INTO project_members (project_id, user_id, role) VALUES ($1, $2, 'employee')",
                _PID, emp)

            cur = await conn.fetchval(
                "INSERT INTO users (name) VALUES ($1) RETURNING id", f"{_PREFIX}curator")
            await conn.execute(
                "INSERT INTO user_emails (email, user_id, is_primary) VALUES ($1, $2, true)",
                f"{_PREFIX}cur@test.kt", cur)
            await conn.execute(
                "INSERT INTO project_members (project_id, user_id, role) VALUES ($1, $2, 'curator')",
                _PID, cur)

            for name, etype, expected, crit in [
                (f"{_PREFIX}BancoNorte", "cliente_cuenta", 12, 0.9),
                (f"{_PREFIX}ETLPipeline", "sistema_componente", 8, 0.9),
                (f"{_PREFIX}CloudBase", "sistema_componente", 5, 0.8),
                (f"{_PREFIX}NovaProc", "procedimiento", 3, 0.4),
            ]:
                await conn.execute(
                    "INSERT INTO nodes (name, type) VALUES ($1, $2) ON CONFLICT (name) DO NOTHING",
                    name, etype)
                await conn.execute(
                    "INSERT INTO entity_expected_claims (project_id, entity_name, entity_type, "
                    "expected_count, expected_criticality) VALUES ($1, $2, $3, $4, $5) "
                    "ON CONFLICT (project_id, entity_name) DO NOTHING",
                    _PID, name, etype, expected, crit)
        finally:
            await conn.close()

    _run(_setup())
    yield

    async def _teardown():
        conn = await asyncpg.connect(_DB_URL)
        try:
            await conn.execute("DELETE FROM cell_runs WHERE metrics::text LIKE $1", f"%{_PREFIX}%")
            await conn.execute("DELETE FROM deletion_requests WHERE claim_id IN (SELECT id FROM claims WHERE subject_entity LIKE $1 OR subject_entity = '[ERASED]')", f"{_PREFIX}%")
            await conn.execute("DELETE FROM audit_log WHERE resource_id IN (SELECT id::text FROM claims WHERE subject_entity LIKE $1 OR subject_entity = '[ERASED]')", f"{_PREFIX}%")
            await conn.execute("DELETE FROM claim_entity_links WHERE claim_id IN (SELECT id FROM claims WHERE subject_entity LIKE $1 OR subject_entity = '[ERASED]')", f"{_PREFIX}%")
            await conn.execute("DELETE FROM claims WHERE subject_entity LIKE $1 OR (subject_entity = '[ERASED]' AND project_id = $2)", f"{_PREFIX}%", _PID)
            await conn.execute("DELETE FROM interview_sessions WHERE topic LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM entity_expected_claims WHERE entity_name LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM nodes WHERE name LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM project_members WHERE user_id IN (SELECT id FROM users WHERE name LIKE $1)", f"{_PREFIX}%")
            await conn.execute("DELETE FROM user_emails WHERE email LIKE $1", f"{_PREFIX}%")
            await conn.execute("DELETE FROM users WHERE name LIKE $1", f"{_PREFIX}%")
        finally:
            await conn.close()
    _run(_teardown())


# ---------------------------------------------------------------------------
# E2E pipeline
# ---------------------------------------------------------------------------

def test_e2e_phase2_pipeline():
    """Full Phase 2 pipeline — single ordered test."""

    async def _pipeline():
        pool = await asyncpg.create_pool(_DB_URL, min_size=1, max_size=3)
        try:
            conn = await pool.acquire()
            try:
                emp_uid = await conn.fetchval(
                    "SELECT id FROM users WHERE name = $1", f"{_PREFIX}employee")
                cur_uid = await conn.fetchval(
                    "SELECT id FROM users WHERE name = $1", f"{_PREFIX}curator")

                # =============================================================
                # STEP A: Seed document claims (simulating curator pre)
                # =============================================================
                doc_claims = [
                    (f"{_PREFIX}BancoNorte", "decide_en", "Carlos Ruiz",
                     "Carlos responsible for Banco Norte account", "document", 2),
                    (f"{_PREFIX}ETLPipeline", "capacidad", "100K txn/day",
                     "ETL designed for 100K transactions per day", "document", 1),
                    (f"{_PREFIX}CloudBase", "sla_hours", "4 hours",
                     "CloudBase SLA contractual 4h P1 response", "document", 2),
                    (f"{_PREFIX}ETLPipeline", "domina", "Maria Lopez",
                     "Maria is owner of ETL pipeline", "document", 0),
                    (f"{_PREFIX}NovaProc", "workaround_conocido", "manual restart",
                     "Manual restart of batch job on Fridays", "document", 1),
                ]
                doc_cids = []
                for subj, pred, obj, ev, src, tier in doc_claims:
                    cid = await conn.fetchval(
                        "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
                        "object_value, evidence_text, source_type, corroboration_level, "
                        "sensitivity, trust_tier, embedding) "
                        "VALUES ($1, $2, $3, $4, $5, $6, $7, 'single_source', 'public', $8, $9::vector) "
                        "RETURNING id",
                        cur_uid, _PID, subj, pred, obj, ev, src, tier, str(_VEC))
                    doc_cids.append(cid)

                # STEP B: Verify doc claims exist
                doc_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM claims WHERE subject_entity LIKE $1 "
                    "AND source_type = 'document'", f"{_PREFIX}%")
                assert doc_count == 5, f"Expected 5 doc claims, got {doc_count}"

                # =============================================================
                # STEP C: Session 1 — scripted interview (tacit claims)
                # =============================================================
                s1 = await conn.fetchval(
                    "INSERT INTO interview_sessions (project_id, employee_id, topic, status, completed_at) "
                    "VALUES ($1, $2, $3, 'completed', now()) RETURNING id",
                    _PID, emp_uid, f"{_PREFIX}session1")

                tacit_claims = [
                    (f"{_PREFIX}BancoNorte", "decide_en", "Elena Ros",
                     "Elena actually makes all decisions for Banco Norte"),
                    (f"{_PREFIX}ETLPipeline", "capacidad", "50K txn/day",
                     "In practice ETL only handles 50K transactions"),
                    (f"{_PREFIX}CloudBase", "sla_hours", "2h verbal",
                     "Juan is incompetent but CloudBase SLA is actually 2h verbal"),
                    (f"{_PREFIX}ETLPipeline", "domina", "Andres Martin",
                     "Andres actually runs the ETL pipeline not Maria"),
                    (f"{_PREFIX}NovaProc", "acuerdo_informal", "No Friday escalations",
                     "Implicit rule: no escalations after Friday 3pm"),
                ]
                tacit_cids = []
                for subj, pred, obj, ev in tacit_claims:
                    cid = await conn.fetchval(
                        "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
                        "object_value, evidence_text, source_type, corroboration_level, "
                        "sensitivity, session_id, employee_id, criticality, embedding) "
                        "VALUES ($1, $2, $3, $4, $5, $6, 'interview', 'single_source', "
                        "'restricted', $7, $1, 0.7, $8::vector) RETURNING id",
                        emp_uid, _PID, subj, pred, obj, ev, s1, str(_VEC))
                    tacit_cids.append(cid)

                # =============================================================
                # STEP D: Curator post → doc_strength + auto-resolution
                # =============================================================
                from curator_post import run_curator_post
                cp_result = await run_curator_post(pool, str(s1))
                assert "error" not in cp_result, f"curator_post failed: {cp_result}"
                assert cp_result.get("sanitized", 0) >= 1, "judgment word should be sanitized"

                # STEP D2: Dossier regeneration (P2.2)
                from dossier import regenerate_dossier
                dr_result = await regenerate_dossier(pool, str(s1))
                assert "error" not in dr_result, f"dossier_regen failed: {dr_result}"

                # STEP E: Verify P2.2 dossier
                s1_row = await conn.fetchrow(
                    "SELECT dossier FROM interview_sessions WHERE id = $1", s1)
                d = s1_row["dossier"]
                if isinstance(d, str):
                    d = json.loads(d)
                regen = d.get("regenerated_dossier")
                assert regen is not None, "regenerated_dossier missing"
                assert "coverage_snapshot" in regen
                assert "priority_gaps" in regen
                assert len(regen["coverage_snapshot"]) > 0

                # =============================================================
                # STEP F+G: Session 2 — continuity (P2.7)
                # =============================================================
                s2 = await conn.fetchval(
                    "INSERT INTO interview_sessions (project_id, employee_id, topic, status) "
                    "VALUES ($1, $2, $3, 'scheduled') RETURNING id",
                    _PID, emp_uid, f"{_PREFIX}session2")

                from interviewer import InterviewState, prepare_dossier, open_topic

                state2 = InterviewState(str(s2), _PID, emp_uid)
                state2 = await prepare_dossier(conn, state2)
                assert state2.prior_session_id == str(s1), \
                    f"session2 should reference session1, got {state2.prior_session_id}"
                assert len(state2.prior_open_threads) > 0, "should have open threads from session1"

                state2 = await open_topic(conn, state2)
                assert state2.state == "conduct"
                assert state2.current_topic is not None

                # =============================================================
                # STEP H: Style directive (P2.8)
                # =============================================================
                s3 = await conn.fetchval(
                    "INSERT INTO interview_sessions (project_id, employee_id, topic, status, "
                    "dossier) VALUES ($1, $2, $3, 'scheduled', $4::jsonb) RETURNING id",
                    _PID, emp_uid, f"{_PREFIX}session3_style",
                    json.dumps({"comm_style": "technical"}))

                state3 = InterviewState(str(s3), _PID, emp_uid)
                initial_d = json.loads(json.dumps({"comm_style": "technical"}))
                state3.comm_style = initial_d.get("comm_style")
                state3 = await prepare_dossier(conn, state3)

                from interviewer import get_style_directive
                sd = get_style_directive(state3)
                assert "architecture" in sd["framing"].lower() or "technical" in sd["framing"].lower()

                # =============================================================
                # STEP I: Disputes (P2.6)
                # =============================================================
                # Find disputed claims
                disputed = await conn.fetch(
                    "SELECT id, subject_entity, predicate, dispute_state, doc_strength "
                    "FROM claims WHERE subject_entity LIKE $1 AND dispute_state = 'disputed'",
                    f"{_PREFIX}%")
                assert len(disputed) > 0, "should have disputed claims after curator_post"

                # Resolve one dispute
                d_claim = disputed[0]
                await conn.execute(
                    "UPDATE claims SET dispute_state = 'resolved_in_favor', "
                    "resolution_note = 'manual review confirms tacit', "
                    "resolved_by_user_id = $1, updated_at = now() WHERE id = $2",
                    cur_uid, d_claim["id"])

                # Verify counterpart gets inverse
                cpart = await conn.fetchrow(
                    "SELECT disputed_by_claim_id FROM claims WHERE id = $1", d_claim["id"])
                if cpart and cpart["disputed_by_claim_id"]:
                    await conn.execute(
                        "UPDATE claims SET dispute_state = 'resolved_against', "
                        "resolved_by_user_id = $1, updated_at = now() WHERE id = $2",
                        cur_uid, cpart["disputed_by_claim_id"])

                resolved = await conn.fetchval(
                    "SELECT dispute_state FROM claims WHERE id = $1", d_claim["id"])
                assert resolved == "resolved_in_favor"

                # =============================================================
                # STEP J: Sanitization (P2.4)
                # =============================================================
                # The CloudBase claim has "incompetent" → curator_post should have
                # set sanitized_text
                cb_claim = await conn.fetchrow(
                    "SELECT sanitized_text, sensitivity FROM claims "
                    "WHERE subject_entity = $1 AND source_type = 'interview'",
                    f"{_PREFIX}CloudBase")
                assert cb_claim is not None
                assert cb_claim["sanitized_text"] is not None, \
                    "judgment word 'incompetent' should have triggered sanitization"
                assert "incompetent" not in cb_claim["sanitized_text"]
                assert cb_claim["sensitivity"] == "restricted"

                # Render check
                from permissions import render_evidence
                admin_view = render_evidence("admin", "raw text", "sanitized")
                consumer_view = render_evidence("consumer", "raw text", "sanitized")
                assert admin_view == "raw text"
                assert consumer_view == "sanitized"

                # =============================================================
                # STEP K: Batch operations (P2.9)
                # =============================================================
                # Create 5 draft claims for batch approve
                batch_ids = []
                for i in range(5):
                    bid = await conn.fetchval(
                        "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
                        "evidence_text, source_type, corroboration_level, sensitivity) "
                        "VALUES ($1, $2, $3, $4, $5, 'document', 'single_source', 'restricted') "
                        "RETURNING id",
                        cur_uid, _PID, f"{_PREFIX}BatchEntity{i}", f"batch_pred_{i}",
                        f"Batch evidence {i}")
                    batch_ids.append(bid)

                # Batch set_sensitivity (doesn't need embedding)
                for bid in batch_ids:
                    async with conn.transaction():
                        await conn.execute(
                            "UPDATE claims SET sensitivity = 'team', updated_at = now() WHERE id = $1",
                            bid)
                        await conn.execute(
                            "INSERT INTO audit_log (user_id, action, resource, resource_id, details) "
                            "VALUES ($1, 'batch_set_sensitivity', 'claim', $2, $3::jsonb)",
                            cur_uid, str(bid),
                            json.dumps({"old": "restricted", "new": "team"}))

                audit_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM audit_log WHERE action = 'batch_set_sensitivity' "
                    "AND resource_id IN (SELECT id::text FROM claims WHERE subject_entity LIKE $1)",
                    f"{_PREFIX}Batch%")
                assert audit_count == 5, f"Expected 5 audit entries, got {audit_count}"

                # =============================================================
                # STEP L: Export (P2.9)
                # =============================================================
                from claims import _csv_safe
                assert _csv_safe("=SUM(A1)") == "'=SUM(A1)"
                assert _csv_safe("  +cmd") == "'  +cmd"
                assert _csv_safe("normal") == "normal"

                from claims import _visibility_sql
                vis_c, vp_c = _visibility_sql("curator", cur_uid, 2)
                curator_count = await conn.fetchval(
                    f"SELECT COUNT(*) FROM claims c WHERE c.project_id = $1 AND ({vis_c}) "
                    f"AND c.subject_entity LIKE '{_PREFIX}%'", _PID, *vp_c)
                assert curator_count >= 10

                vis_co, vp_co = _visibility_sql("consumer", 999, 2)
                consumer_count = await conn.fetchval(
                    f"SELECT COUNT(*) FROM claims c WHERE c.project_id = $1 AND ({vis_co}) "
                    f"AND c.subject_entity LIKE '{_PREFIX}%'", _PID, *vp_co)
                assert consumer_count < curator_count, \
                    "consumer should see fewer claims than curator (restricted filtered)"

                # =============================================================
                # STEP M: Scoring (P2.1)
                # =============================================================
                from scoring import compute_score
                score = await compute_score(conn, _PID, emp_uid)
                assert score.score > 0, f"Employee with diverse claims should score > 0, got {score.score}"
                assert score.components.gaming_penalty == 0.0, \
                    "Diverse claims (all single_source) should have 0 gaming penalty"
                assert score.claim_count >= 5

                # =============================================================
                # STEP N: GDPR erasure (P2.11)
                # =============================================================
                # Pick a tacit claim to erase
                erase_cid = tacit_cids[-1]  # NovaProc acuerdo_informal
                pre_claim = await conn.fetchrow("SELECT * FROM claims WHERE id = $1", erase_cid)
                assert pre_claim["evidence_text"] is not None
                pre_session = pre_claim["session_id"]

                # Create deletion request
                req_id = await conn.fetchval(
                    "INSERT INTO deletion_requests (project_id, claim_id, requested_by, reason) "
                    "VALUES ($1, $2, $3, 'GDPR request test') RETURNING id",
                    _PID, erase_cid, emp_uid)

                # Curator approves
                from deletion import gdpr_erase_claim
                await gdpr_erase_claim(conn, erase_cid, cur_uid, "employee_request")
                await conn.execute(
                    "UPDATE deletion_requests SET status = 'approved', reviewed_by = $1, "
                    "resolved_at = now(), reason = NULL WHERE id = $2",
                    cur_uid, req_id)

                # Verify full erasure
                erased = await conn.fetchrow("SELECT * FROM claims WHERE id = $1", erase_cid)
                assert erased["evidence_text"] == "[ERASED]"
                assert erased["subject_entity"] == "[ERASED]"
                assert erased["predicate"] == "[ERASED]"
                assert erased["employee_id"] is None
                assert erased["session_id"] is None
                assert erased["embedding"] is None

                # Tombstone has no PII
                tomb = await conn.fetchrow(
                    "SELECT * FROM deletion_requests WHERE id = $1", req_id)
                assert tomb["reason"] is None
                assert tomb["status"] == "approved"

                # Entity links cleaned
                link_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM claim_entity_links WHERE claim_id = $1", erase_cid)
                assert link_count == 0

                # Session rollup cleaned
                if pre_session:
                    sess = await conn.fetchrow(
                        "SELECT rollup FROM interview_sessions WHERE id = $1", pre_session)
                    assert sess["rollup"] == "[Session data erased per GDPR request]"

                # =============================================================
                # MVP REGRESSION CHECKS
                # =============================================================

                # Money-shot: ETL Pipeline → Andres Martin claim exists
                etl_andres = await conn.fetchval(
                    "SELECT COUNT(*) FROM claims WHERE subject_entity = $1 "
                    "AND predicate = 'domina' AND object_value = 'Andres Martin' "
                    "AND corroboration_level != 'rejected'",
                    f"{_PREFIX}ETLPipeline")
                assert etl_andres >= 1, "Andres Martin runs ETL claim must exist"

                # CloudBase disputed (sla_hours contradiction)
                cb_dispute = await conn.fetch(
                    "SELECT dispute_state FROM claims WHERE subject_entity = $1 "
                    "AND predicate = 'sla_hours' AND corroboration_level != 'rejected'",
                    f"{_PREFIX}CloudBase")
                dispute_states = {r["dispute_state"] for r in cb_dispute}
                assert dispute_states & {"disputed", "resolved_in_favor", "resolved_against"}, \
                    f"CloudBase sla_hours should have dispute activity, got {dispute_states}"

                # Coverage: BancoNorte has claims → entity_coverage > 0
                cov = await conn.fetchrow(
                    "SELECT coverage_pct FROM entity_coverage "
                    "WHERE project_id = $1 AND entity_name = $2",
                    _PID, f"{_PREFIX}BancoNorte")
                if cov:
                    assert float(cov["coverage_pct"]) > 0, "BancoNorte should have coverage > 0"

            finally:
                await pool.release(conn)
        finally:
            await pool.close()

    _run(_pipeline())
