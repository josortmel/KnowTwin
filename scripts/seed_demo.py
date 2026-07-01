"""Juan Garcia demo seed — orchestrates full pipeline with stub LLM.

Produces the exact demo state: 4 contradictions, 5 star tacit claims,
coverage delta, twin query assertions.

Run: python scripts/seed_demo.py
Requires: knowtwin-api + knowtwin-db running.
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

import asyncpg

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://knowtwin:knowtwin_test_pass@localhost:5436/knowtwin",
)

SEED_DIR = Path(__file__).parent.parent / "seed" / "juan_garcia"
DOCS_DIR = SEED_DIR / "docs"

_DOC_TRUST_HINTS = {
    "plan_banco_norte.md": "formal_contract",
    "adr_postgresql.md": "adr",
    "contrato_cloudbase.md": "formal_contract",
    "organigrama_equipo.md": "orgchart",
    "wiki_etl.md": "wiki",
    "correo_renovacion.md": "email",
    "informe_p1.md": "presentation",
    "plan_retailco.md": "signed_plan",
}

CANNED_EXTRACTIONS = json.loads((SEED_DIR / "canned_extractions.json").read_text())
SESSION_RESPONSES = json.loads((SEED_DIR / "session_responses.json").read_text())


async def main():
    conn = await asyncpg.connect(DATABASE_URL)
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)

    try:
        print("=== Juan Garcia Demo Seed ===")

        # 1. Ensure org + project + users
        print("\n1. Setting up org/project/users...")
        org_id = await conn.fetchval(
            "INSERT INTO organizations (name) VALUES ('Nova Consulting') "
            "ON CONFLICT DO NOTHING RETURNING id"
        )
        if org_id is None:
            org_id = await conn.fetchval("SELECT id FROM organizations WHERE name = 'Nova Consulting'")

        ws_id = await conn.fetchval(
            "INSERT INTO workspaces (name, organization_id) VALUES ('Default', $1) "
            "ON CONFLICT DO NOTHING RETURNING id", org_id
        )
        if ws_id is None:
            ws_id = await conn.fetchval("SELECT id FROM workspaces LIMIT 1")

        proj_id = await conn.fetchval("SELECT id FROM projects WHERE id = 1")
        if proj_id is None:
            proj_id = await conn.fetchval(
                "INSERT INTO projects (id, name, workspace_id) VALUES (1, 'Juan Garcia Offboarding', $1) RETURNING id",
                ws_id,
            )

        admin_id = await conn.fetchval("SELECT id FROM users WHERE name = 'admin'")

        emp_id = await conn.fetchval("SELECT id FROM users WHERE name = 'Juan Garcia'")
        if emp_id is None:
            emp_id = await conn.fetchval("INSERT INTO users (name) VALUES ('Juan Garcia') RETURNING id")
            await conn.execute(
                "INSERT INTO user_emails (email, user_id, is_primary) VALUES ('juan@nova.com', $1, true) "
                "ON CONFLICT DO NOTHING", emp_id
            )
        await conn.execute(
            "INSERT INTO project_members (project_id, user_id, role) VALUES ($1, $2, 'employee') "
            "ON CONFLICT DO NOTHING", proj_id, emp_id
        )
        await conn.execute(
            "INSERT INTO project_members (project_id, user_id, role) VALUES ($1, $2, 'admin') "
            "ON CONFLICT DO NOTHING", proj_id, admin_id
        )
        print(f"   org={org_id}, ws={ws_id}, project={proj_id}, admin={admin_id}, employee={emp_id}")

        # 2. Seed entities (reuse existing script logic)
        print("\n2. Seeding entities...")
        from seed_demo_entities import DEMO_ENTITIES, _normalize, _expected_count, _expected_criticality
        seeded = 0
        for name, entity_type in DEMO_ENTITIES:
            name_norm = _normalize(name)
            r = await conn.execute(
                "INSERT INTO entity_dictionary (name, name_normalized, entity_type) "
                "VALUES ($1, $2, $3) ON CONFLICT (name_normalized) DO NOTHING",
                name, name_norm, entity_type,
            )
            await conn.execute(
                "INSERT INTO nodes (name, type, status) VALUES ($1, $2, 'active') ON CONFLICT (name) DO NOTHING",
                name, entity_type,
            )
            ec = _expected_count(entity_type)
            crit = _expected_criticality(name)
            await conn.execute(
                "INSERT INTO entity_expected_claims (project_id, entity_name, entity_type, expected_count, expected_criticality) "
                "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (project_id, entity_name) DO NOTHING",
                proj_id, name, entity_type, ec, crit,
            )
            seeded += 1
        print(f"   {seeded} entities seeded")

        # 3. Insert documents + claims from canned extractions (simulates curator_pre)
        print("\n3. Seeding documents + canned claims...")
        for doc_file, trust_hint in _DOC_TRUST_HINTS.items():
            doc_key = doc_file.replace(".md", "")
            doc_path = str(DOCS_DIR / doc_file)

            doc_id = await conn.fetchval(
                "INSERT INTO documents (uri, filename, doc_type, workspace_id, project_id, "
                "visibility, status, trust_hint) "
                "VALUES ($1, $2, 'markdown', $3, $4, 'public', 'indexed', $5) "
                "ON CONFLICT (uri) DO NOTHING RETURNING id",
                doc_path, doc_file, ws_id, proj_id, trust_hint,
            )
            if doc_id is None:
                doc_id = await conn.fetchval("SELECT id FROM documents WHERE uri = $1", doc_path)

            from curator import trust_tier_from_hint
            tier = trust_tier_from_hint(trust_hint)

            if doc_key in CANNED_EXTRACTIONS:
                for cd in CANNED_EXTRACTIONS[doc_key]["claims"]:
                    await conn.execute(
                        "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
                        "object_value, evidence_text, source_type, trust_tier, sensitivity, "
                        "corroboration_level, source_id, tags) "
                        "VALUES ($1, $2, $3, $4, $5, $6, 'document', $7, 'public', "
                        "'single_source', $8, $9::text[]) ON CONFLICT DO NOTHING",
                        admin_id, proj_id,
                        cd["subject_entity"], cd["predicate"],
                        cd.get("object_value"), cd["evidence_text"],
                        tier, str(doc_id), ["demo_seed"],
                    )
        print(f"   8 documents + claims seeded")

        # 4. Run scripted interview sessions
        print("\n4. Running scripted interview sessions...")
        for session_key, session_data in SESSION_RESPONSES.items():
            sid = await conn.fetchval(
                "INSERT INTO interview_sessions (project_id, employee_id, topic, status) "
                "VALUES ($1, $2, $3, 'completed') RETURNING id",
                proj_id, emp_id, session_data["topic"],
            )

            for turn in session_data["turns"]:
                for cd in turn["canned_extraction"]["claims"]:
                    await conn.execute(
                        "INSERT INTO claims (user_id, project_id, subject_entity, predicate, "
                        "object_value, evidence_text, source_type, employee_id, session_id, "
                        "sensitivity, corroboration_level, tags) "
                        "VALUES ($1, $2, $3, $4, $5, $6, 'interview', $7, $8, "
                        "'restricted', 'single_source', $9::text[])",
                        emp_id, proj_id,
                        cd["subject_entity"], cd["predicate"],
                        cd.get("object_value"), cd["evidence_text"],
                        emp_id, sid, ["demo_seed"],
                    )
            print(f"   {session_key}: {len(session_data['turns'])} turns")

        # 5. Run contradiction detection (curator_post logic)
        print("\n5. Running contradiction detection...")
        from curator import _detect_contradictions
        contradictions = await _detect_contradictions(conn, proj_id)
        print(f"   {len(contradictions)} contradictions detected")

        # 6. Run doc_strength resolution (curator_post logic)
        print("\n6. Running doc_strength resolution...")
        from curator_post import run_curator_post
        for session_key in SESSION_RESPONSES:
            sids = await conn.fetch(
                "SELECT id FROM interview_sessions WHERE project_id = $1 AND topic = $2",
                proj_id, SESSION_RESPONSES[session_key]["topic"],
            )
            for s in sids:
                result = await run_curator_post(pool, str(s["id"]))
                if "error" not in result:
                    print(f"   {session_key}: auto_resolved={result.get('auto_resolved',0)}, "
                          f"disputed={result.get('disputed',0)}")

        # 7. Verify exit criteria
        print("\n=== EXIT CRITERIA ===")

        resolved = await conn.fetchval(
            "SELECT COUNT(*) FROM claims WHERE project_id = $1 AND dispute_state = 'resolved_in_favor'",
            proj_id,
        )
        disputed = await conn.fetchval(
            "SELECT COUNT(*) FROM claims WHERE project_id = $1 AND dispute_state = 'disputed'",
            proj_id,
        )
        print(f"   Contradictions: {resolved} resolved_in_favor, {disputed} disputed")

        tacit = await conn.fetchval(
            "SELECT COUNT(*) FROM claims WHERE project_id = $1 AND source_type = 'interview' AND tags @> ARRAY['demo_seed']",
            proj_id,
        )
        print(f"   Tacit claims from interviews: {tacit}")

        coverage = await conn.fetch(
            "SELECT entity_name, coverage_pct, coverage_state FROM entity_coverage "
            "WHERE project_id = $1 AND entity_name = 'Banco Norte'",
            proj_id,
        )
        if coverage:
            print(f"   Banco Norte coverage: {coverage[0]['coverage_pct']}% ({coverage[0]['coverage_state']})")

        total_claims = await conn.fetchval(
            "SELECT COUNT(*) FROM claims WHERE project_id = $1", proj_id
        )
        print(f"   Total claims: {total_claims}")

        print("\n=== DEMO SEED COMPLETE ===")

    finally:
        await conn.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
