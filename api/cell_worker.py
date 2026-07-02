"""KnowTwin Cell Worker — batch task runner.

Runs registered cell types (curator_pre, verifier) via _BUILTIN_DISPATCH.
EcoDB metacognition builtins (consolidation/foresight/skill) stripped.
"""
import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone

import asyncpg
import httpx
log = logging.getLogger("knowtwin.cell")

DATABASE_URL = os.environ["DATABASE_URL"]
API_URL = os.environ.get("KNOWTWIN_API_INTERNAL_URL", os.environ.get("ECODB_API_INTERNAL_URL", "http://knowtwin-api:8080"))
_INTERNAL_SECRET = os.environ.get("INTERNAL_BROADCAST_SECRET", "")

_CELL_LLM = None
CELL_MODEL = os.environ.get("CELL_LLM_MODEL", "deepseek-v4-pro")
_t = os.environ.get("CELL_LLM_TIMEOUT", "").strip().lower()
CELL_LLM_TIMEOUT = None if _t in ("", "0", "none") else float(_t)
CELL_LLM_MAX_TOKENS = int(os.environ.get("CELL_LLM_MAX_TOKENS", "32768"))
MAX_LLM_RETRIES = 3
LLM_DELAYS = [30, 60, 120]


import string as _string


class _SafeFormatter(_string.Formatter):
    """Formatter that blocks attribute (.x) and index ([x]) access in field names."""
    def get_field(self, field_name, args, kwargs):
        if "." in field_name or "[" in field_name:
            raise ValueError(f"attribute/index access not allowed in template: {field_name!r}")
        return super().get_field(field_name, args, kwargs)

    def get_value(self, key, args, kwargs):
        if isinstance(key, str):
            return kwargs.get(key, "")
        return super().get_value(key, args, kwargs)


_SAFE_FMT = _SafeFormatter()


def _safe_format(template: str, **kwargs) -> str:
    return _SAFE_FMT.vformat(template, (), kwargs)


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------

def _lock_key(agent_id, cell_type, p_start, p_end):
    raw = f"{agent_id}:{cell_type}:{p_start}:{p_end}"
    return int(hashlib.sha256(raw.encode()).hexdigest()[:15], 16)


async def _check_idempotency(conn, agent_id, cell_type, p_start, p_end,
                             cluster_level=None):
    rows = await conn.fetch("""
        SELECT status, items_created FROM cell_runs
        WHERE agent_id=$1 AND cell_type=$2
          AND status IN ('completed', 'running')
          AND metrics->>'period_start' = $3
          AND metrics->>'period_end' = $4
    """, agent_id, cell_type, str(p_start), str(p_end))
    if not rows:
        return False
    if any(r["status"] == "running" for r in rows):
        return True
    return True


async def _create_run(conn, cell_type, agent_id, p_start, p_end):
    return await conn.fetchval("""
        INSERT INTO cell_runs (cell_type, agent_id, model, prompt_version, metrics)
        VALUES ($1, $2, $3, $4, $5::jsonb) RETURNING id
    """, cell_type, agent_id, _active_model(), _active_prompt_version(),
        json.dumps({"period_start": str(p_start), "period_end": str(p_end)}))


async def _complete_run(conn, run_id, items_created):
    pv = _active_prompt_version()
    mdl = _active_model()
    await conn.execute("""
        UPDATE cell_runs SET finished_at=NOW(), status='completed',
          items_created=$2, prompt_version=$3, model=$4
        WHERE id=$1 AND status='running'
    """, run_id, items_created, pv, mdl)


async def _fail_run(conn, run_id, error):
    if isinstance(error, BaseException):
        msg = str(error) or type(error).__name__
    else:
        msg = str(error) or "unknown (empty error message)"
    await conn.execute("""
        UPDATE cell_runs SET finished_at=NOW(), status='failed',
          errors = errors || jsonb_build_array($2::jsonb)
        WHERE id=$1 AND status='running'
    """, run_id, json.dumps({
        "error": msg[:500],
        "at": datetime.now(timezone.utc).isoformat()
    }))


async def _broadcast_sse(event_type, data, org_id=None):
    try:
        headers = {"X-Internal-Secret": _INTERNAL_SECRET} if _INTERNAL_SECRET else {}
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{API_URL}/api/v1/events/broadcast",
                json={"event_type": event_type, "data": data, "org_id": org_id},
                headers=headers)
    except Exception:
        pass


async def _load_cell_config(conn, agent_id, cell_type, level=None):
    """Load config from DB. Fallback to env vars if no row."""
    row = await conn.fetchrow("""
        SELECT ctc.*, cpt.content AS prompt_content, cpt.name AS prompt_name
        FROM cell_task_configs ctc
        LEFT JOIN cell_prompt_templates cpt ON cpt.id = ctc.prompt_template_id
        WHERE ctc.agent_id = $1 AND ctc.cell_type = $2
          AND (ctc.level IS NOT DISTINCT FROM $3) AND ctc.enabled = true
    """, agent_id, cell_type, level)
    if row is None:
        return {
            "model": CELL_MODEL,
            "provider": "deepseek",
            "prompt_content": None,
            "prompt_name": None,
            "config": {},
        }
    cfg = dict(row)
    if isinstance(cfg.get("config"), str):
        cfg["config"] = json.loads(cfg["config"])
    return cfg


async def _llm_retry(func, *args):
    for attempt in range(MAX_LLM_RETRIES):
        try:
            return await func(*args)
        except Exception as e:
            if attempt < MAX_LLM_RETRIES - 1:
                delay = LLM_DELAYS[attempt]
                log.warning("LLM attempt %d failed: %r, retry in %ds",
                           attempt + 1, e, delay)
                await asyncio.sleep(delay)
            else:
                raise


async def recover_stuck_runs(pool, timeout_min=60):
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE cell_runs SET status='failed', finished_at=NOW(),
              errors = errors || '["stuck_recovery"]'::jsonb
            WHERE status='running'
              AND started_at < NOW() - ($1 || ' minutes')::interval
        """, str(timeout_min))
        count = int(result.split()[-1]) if result else 0
        if count:
            log.warning("Recovered %d stuck cell runs", count)


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------

async def _llm_call(system_prompt: str, user_prompt: str) -> str:
    _ctx = _active_cell.get()
    if _ctx and _ctx.get("key"):
        return await _llm_call_with_key(
            system_prompt, user_prompt,
            _ctx.get("provider", "deepseek"),
            _ctx.get("model", CELL_MODEL),
            _ctx["key"])

    global _CELL_LLM
    if _CELL_LLM is None:
        try:
            from ecodb_langchain.cell_agent import make_cell_llm, acell_llm_call as _acell
            _CELL_LLM = make_cell_llm()
            _llm_call._acell = _acell
            log.info("Cell LLM: using LangChain engine")
        except ImportError:
            _CELL_LLM = "httpx_fallback"
            log.info("Cell LLM: ecodb-langchain not installed, using httpx fallback")
    if _CELL_LLM == "httpx_fallback":
        return await _llm_call_httpx(system_prompt, user_prompt)
    return await _llm_call._acell(system_prompt, user_prompt, llm=_CELL_LLM)


async def _llm_call_httpx(system_prompt: str, user_prompt: str) -> str:
    _key = os.environ.get("CELL_LLM_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
    _url = os.environ.get("CELL_LLM_URL", "https://api.deepseek.com")
    _model = os.environ.get("CELL_LLM_MODEL", "deepseek-chat")
    headers = {"Authorization": f"Bearer {_key}", "Content-Type": "application/json"}
    body = {
        "model": _model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": CELL_LLM_MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=CELL_LLM_TIMEOUT) as client:
        resp = await client.post(f"{_url}/v1/chat/completions", json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _get_provider_key(conn, provider: str) -> str:
    """DB key first (decrypt via crypto), env var fallback."""
    row = await conn.fetchrow(
        "SELECT api_key_encrypted FROM llm_provider_keys WHERE provider=$1",
        provider)
    if row:
        import crypto
        try:
            return crypto.decrypt(row["api_key_encrypted"])
        except Exception as dec_err:
            log.error("Provider key for '%s' cannot be decrypted (ENCRYPTION_KEY rotated?): %s",
                      provider, dec_err)
    env_key = os.environ.get(f"{provider.upper()}_API_KEY", "")
    if not env_key:
        env_key = os.environ.get("CELL_LLM_KEY", "")
    if not env_key:
        if row:
            raise RuntimeError(
                f"Provider key for '{provider}' cannot be decrypted — ENCRYPTION_KEY may have "
                f"been rotated. Re-encrypt stored keys or restore the original key. "
                f"No env-var fallback ({provider.upper()}_API_KEY) is set.")
        raise RuntimeError(f"No API key for provider '{provider}' — neither DB nor env var")
    return env_key


_PROVIDER_URLS = {
    "deepseek": "https://api.deepseek.com",
    "anthropic": "https://api.anthropic.com",
}

import contextvars as _contextvars
_active_cell: "_contextvars.ContextVar[dict | None]" = _contextvars.ContextVar("active_cell", default=None)


def _active_model() -> str:
    _ctx = _active_cell.get()
    return _ctx["model"] if _ctx and _ctx.get("model") else CELL_MODEL


def _active_prompt_version():
    _ctx = _active_cell.get()
    return _ctx.get("prompt_name") if _ctx else None


def _active_prompt(default_prompt: str) -> str:
    _ctx = _active_cell.get()
    if _ctx and _ctx.get("template"):
        return _safe_format(_ctx["template"])
    return default_prompt


async def _llm_call_with_key(system_prompt: str, user_prompt: str,
                              provider: str, model: str, key: str) -> str:
    """Provider routing given an already-resolved key (no DB lookup)."""
    if provider == "anthropic":
        headers = {"x-api-key": key, "content-type": "application/json",
                   "anthropic-version": "2023-06-01"}
        body = {
            "model": model,
            "max_tokens": CELL_LLM_MAX_TOKENS,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": 0.3,
        }
        async with httpx.AsyncClient(timeout=CELL_LLM_TIMEOUT) as client:
            resp = await client.post(f"{_PROVIDER_URLS['anthropic']}/v1/messages",
                                     json=body, headers=headers)
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]
    url = _PROVIDER_URLS.get(provider, f"https://api.{provider}.com")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": CELL_LLM_MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=CELL_LLM_TIMEOUT) as client:
        resp = await client.post(f"{url}/v1/chat/completions", json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Dispatch table — KnowTwin cell types
# ---------------------------------------------------------------------------

def _curator_pre_handler(pool, aid, cfg, ps, pe):
    from curator import run_curator_pre
    return run_curator_pre(pool, cfg.get("project_id", 1), aid)


def _verifier_handler(pool, aid, cfg, ps, pe):
    from verifier import run_verifier
    return run_verifier(pool, cfg.get("project_id", 1), aid)


def _curator_post_handler(pool, aid, cfg, ps, pe):
    from curator_post import run_curator_post
    return run_curator_post(pool, cfg.get("session_id", ""))


def _dossier_regen_handler(pool, aid, cfg, ps, pe):
    from dossier import regenerate_dossier
    return regenerate_dossier(pool, cfg.get("session_id", ""))


def _retention_expiry_handler(pool, aid, cfg, ps, pe):
    from deletion import run_retention_expiry
    return run_retention_expiry(pool, cfg.get("project_id", 1))


_BUILTIN_DISPATCH = {
    ("curator_pre", None): _curator_pre_handler,
    ("curator_post", None): _curator_post_handler,
    ("dossier_regen", None): _dossier_regen_handler,
    ("retention_expiry", None): _retention_expiry_handler,
    ("verifier", None): _verifier_handler,
}


async def start_curator_post_listener(pool):
    """LISTEN on knowtwin_curator_post channel for post-session triggers."""
    conn = await pool.acquire()
    try:
        await conn.add_listener("knowtwin_curator_post", lambda *args: None)
        import asyncio
        while True:
            notif = await conn.connection.notifies.get()
            session_id = notif.payload
            log.info("curator_post triggered for session %s", session_id)
            try:
                from curator_post import run_curator_post
                await run_curator_post(pool, session_id)
            except Exception as exc:
                log.warning("curator_post failed for session %s: %r", session_id, exc)
    finally:
        await pool.release(conn)


async def start_dossier_regen_listener(pool):
    """LISTEN on knowtwin_dossier_regen channel for post-curator dossier refresh."""
    conn = await pool.acquire()
    try:
        await conn.add_listener("knowtwin_dossier_regen", lambda *args: None)
        import asyncio
        while True:
            notif = await conn.connection.notifies.get()
            session_id = notif.payload
            log.info("dossier_regen triggered for session %s", session_id)
            try:
                from dossier import regenerate_dossier
                await regenerate_dossier(pool, session_id)
            except Exception as exc:
                log.warning("dossier_regen failed for session %s: %r", session_id, exc)
    finally:
        await pool.release(conn)
