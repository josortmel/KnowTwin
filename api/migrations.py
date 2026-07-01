"""Idempotent migration runner for EcoDB.

Applies pending SQL migrations on every API startup. All migrations
are idempotent (IF NOT EXISTS / OR REPLACE / ON CONFLICT DO NOTHING),
so re-applying is a no-op on an up-to-date schema.

Runs inside the FastAPI lifespan, after validate_production_secrets()
and before the dictionary cache. Uses pg_advisory_lock to serialize
concurrent startups (future multi-replica).
"""
import logging
import time
from pathlib import Path

import settings

log = logging.getLogger("ecodb.migrations")

MIGRATIONS: list[tuple[str, str]] = [
    ("3_0h_multimodal",   "sql/migrate_3_0h_multimodal.sql"),
    ("5.1.0_multitenant", "sql/migrate_5.0.1_to_5.1.0.sql"),
    ("5.1.1_clusters",    "sql/migrate_5.1.0_to_5.1.1.sql"),
    ("age_sync_triggers", "sql/trigger_age_sync.sql"),
    # --- Metacognicion ---
    ("5.2.0_foresight",      "sql/migrate_06_foresight.sql"),
    ("5.2.0_types_schema",   "sql/migrate_07a_types_schema.sql"),
    ("5.2.0_types_config",   "sql/migrate_07b_types_config.sql"),
    ("5.2.0_agents",         "sql/migrate_08_agents.sql"),
    ("5.2.0_metacognition",  "sql/migrate_09_metacognition.sql"),
    # --- Memory Agent v1.3 ---
    ("5.3.0_memory_agent",   "sql/migrate_5.2.0_to_5.3.0_memory_agent.sql"),
    ("5.3.0_memory_agent_seed", "sql/seed_memory_agent.sql"),
    # Level-specific higher-consolidation prompts (monthly/quarterly/yearly) + config rewire.
    ("5.3.0_higher_prompts", "sql/seed_higher_prompts.sql"),
    # v2: per-section word budgets + completeness check (v4-pro undershot
    # global targets — Eco's quarterly came out at 1/3 of the 2500-word floor).
    ("5.3.1_higher_prompts_v2", "sql/seed_higher_prompts_v2.sql"),
]

_LOCK_KEY = 728_1990


async def run_migrations(pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute("SELECT pg_advisory_lock($1)", _LOCK_KEY, timeout=600)
        try:
            for name, path in MIGRATIONS:
                sql = Path(path).read_text(encoding="utf-8")
                t0 = time.monotonic()
                try:
                    await conn.execute(sql, timeout=300)
                except Exception:
                    log.error("migration FAILED: %s", name)
                    raise
                elapsed = (time.monotonic() - t0) * 1000
                log.info("migration OK: %s (%.0f ms)", name, elapsed)
            log.info("schema at target %s", settings.SCHEMA_VERSION)
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", _LOCK_KEY)
