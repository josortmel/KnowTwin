"""
KnowTwin API.

Endpoints en este sprint:
- GET  /health        — liveness check, sin dependencias externas, siempre 200 OK.
- HEAD /health        — RFC 7231 §4.3.2.
- POST /auth/token    — intercambio API key → JWT (TTL configurable).
- GET  /auth/me       — claims del usuario actual.
- POST /auth/api-keys — crear nuevas API keys (super o CEO).

Hardening de seguridad:
- docs/redoc/openapi gated por ENVIRONMENT (production = cerrado).
- X-Content-Type-Options + Referrer-Policy en TODAS las
  respuestas, Server header suprimido a nivel uvicorn (--no-server-header).
- CORS restrictivo — origins explicitos, credentials=False.
- SecurityHeadersMiddleware en ASGI puro: los headers se aplican siempre,
  incluso en respuestas 500 originadas por excepciones no-HTTP.

Pendiente (deuda anotada):
- VS4 → mover api_version/schema_version a /admin/health (Fase 2).
- VS6 → pip-compile --generate-hashes antes de imagen de produccion.
- VS9 → rate limiting (slowapi) antes de VPS.
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import settings
import auth as auth_module
from db import close_pool, get_pool


# ---------------------------------------------------------------------------
# SecurityHeadersMiddleware ASGI puro.
# BaseHTTPMiddleware tenia un edge case con excepciones no-HTTPException que
# saltaba el middleware. ASGI puro intercepta http.response.start ANTES de
# que el body se serialice — los headers se aplican siempre, incluso en 500.
# ---------------------------------------------------------------------------

class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def patched_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                ct = headers.get("content-type", "")
                if ct.startswith("application/json") and "charset" not in ct:
                    headers["content-type"] = "application/json; charset=utf-8"
            await send(message)

        await self.app(scope, receive, patched_send)


# ---------------------------------------------------------------------------
# Lifespan: abrir pool al arrancar, cerrarlo al apagar.
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validacion de secretos en production al startup (no al import — eso
    # rompia tests). En development es no-op.
    settings.validate_production_secrets()
    import logging as _startup_logging
    _ecodb_log = _startup_logging.getLogger("ecodb")
    _ecodb_log.setLevel(_startup_logging.INFO)
    if not _ecodb_log.handlers:
        _h = _startup_logging.StreamHandler()
        _h.setFormatter(_startup_logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        _ecodb_log.addHandler(_h)
    # Si DATABASE_URL apunta a un host que aun no existe (tests, builds en CI),
    # arrancar igual y dejar que el pool falle al primer endpoint que lo use.

    # 
    # lookup-first (consenso adv-code 2026-05-09: cache RAM al arranque vs
    # query per-call cuando E llama al diccionario en CADA POST /memories
    # + ráfaga de 946 memorias en migración 3.0c).
    # Endpoint /admin/entity-dictionary/reload (super-only) para invalidacion
    # explícita post-CRUD.
    # Si BD no esta disponible (tests CI sin postgres), la carga falla
    # silenciosa y el cache queda vacío — extract_entities sigue funcionando
    # sin override (solo GLiNER puro).
    # KnowTwin uses a single CONSOLIDATED init.sql (all DDL folded in) applied by
    # docker-entrypoint-initdb.d on an empty volume — there is NO migration runner
    # (EcoDB day-94 fresh-install lesson). Schema is born at its final version.
    try:
        from gliner_service import load_dictionary_to_cache
        pool = await get_pool()
        count = await load_dictionary_to_cache(pool)
        import logging
        logging.getLogger("ecodb.startup").info(
            "entity_dictionary cache loaded at startup: %d entries", count
        )
    except Exception as exc:
        import logging
        logging.getLogger("ecodb.startup").warning(
            "entity_dictionary cache load failed at startup (extract_entities will run without overrides): %r", exc
        )

    # LLM provider init (Adendum A)
    from llm_provider import init_llm_provider
    llm = init_llm_provider()
    if llm:
        is_avail = await llm.available()
        _ecodb_log.info("LLM provider %s: available=%s", settings.ECODB_LLM_PROVIDER, is_avail)

    # In-process document ingestion (P1.8): recover stuck + start LISTEN loop
    _ingest_task = None
    try:
        from worker import recover_stuck_documents, start_ingest_listener
        pool = await get_pool()
        await recover_stuck_documents(pool)
        _ingest_task = asyncio.create_task(start_ingest_listener(pool))
        _ecodb_log.info("Ingest listener started on channel knowtwin_ingest")
    except Exception as _ingest_exc:
        _ecodb_log.warning(
            "Ingest listener startup failed (documents won't auto-process): %r", _ingest_exc
        )

    yield

    if _ingest_task is not None:
        _ingest_task.cancel()
        try:
            await _ingest_task
        except (asyncio.CancelledError, Exception):
            pass
    from llm_provider import get_llm_provider
    llm = get_llm_provider()
    if llm and hasattr(llm, "aclose"):
        await llm.aclose()
    await close_pool()


# ---------------------------------------------------------------------------
# Factory: crea la app con la configuracion del entorno dado.
# ---------------------------------------------------------------------------

def create_app(environment: str = None) -> FastAPI:
    if environment is None:
        environment = settings.ENVIRONMENT
    docs_enabled = environment.lower() == "development"

    app = FastAPI(
        title="KnowTwin API",
        version=settings.API_VERSION,
        description="Tacit-knowledge capture over a claims graph (PostgreSQL + pgvector + AGE + Jina v4).",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )

    # VS7: CORS restrictivo — origins explicitos, credentials=False (tokens van
    # en Authorization header, no cookies, asi que no hace falta credentials).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "HEAD", "PATCH"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # VS5 + NV1: security headers via ASGI puro.
    app.add_middleware(SecurityHeadersMiddleware)

    # VS9: rate limiting in-memory por actor+path.
    from rate_limit import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)

    import json as _json
    import httpx as _httpx

    from settings import EMBEDDINGS_URL as _EMBEDDINGS_URL_SETTING
    _EMBEDDINGS_HEALTH_URL = _EMBEDDINGS_URL_SETTING + "/health"

    @app.get("/health", tags=["health"], operation_id="health_liveness")
    async def health() -> Response:
        embeddings_status = "ok"
        try:
            async with _httpx.AsyncClient(timeout=3.0) as _client:
                _r = await _client.get(_EMBEDDINGS_HEALTH_URL)
                if _r.status_code != 200:
                    embeddings_status = "degraded"
        except Exception as _e:
            import logging as _logging
            _logging.getLogger("ecodb.health").warning(
                "embeddings health check failed: %s", type(_e).__name__
            )
            embeddings_status = "degraded"
        llm_status = "off"
        if settings.ECODB_LLM_PROVIDER != "off":
            from llm_provider import get_llm_provider
            llm = get_llm_provider()
            if llm:
                try:
                    llm_avail = await llm.available()
                    llm_status = "ok" if llm_avail else "degraded"
                except Exception:
                    llm_status = "degraded"
            else:
                llm_status = "not_configured"
        body = _json.dumps({
            "status": "ok",
            "service": "knowtwin-api",
            "api_version": settings.API_VERSION,
            "schema_version_target": settings.SCHEMA_VERSION,
            "embeddings": embeddings_status,
            "llm": llm_status,
        }).encode("utf-8")
        return Response(content=body, media_type="application/json", status_code=200)

    @app.head("/health", include_in_schema=False)
    async def health_head() -> Response:
        return Response(status_code=200, media_type="application/json")

    # Auth router (.
    app.include_router(auth_module.router)

    # Memories router (EcoDB legacy — dead code, claims table replaces memories).
    import memories
    app.include_router(memories.router)

    # Claims router (KnowTwin — embed gate).
    import claims
    app.include_router(claims.router)

    # Graph router ( — SQL + AGE atomico.
    import graph
    app.include_router(graph.router)

    # Search router ( — busqueda semantica basica = Etapa 3 GAMR.
    import search
    app.include_router(search.router)

    # Workspaces router ( — CRUD workspaces con cascada permisos.
    import workspaces
    app.include_router(workspaces.router)

    # Projects router ( — CRUD projects con cascada heredada de 2.1.
    import projects
    app.include_router(projects.router)

    # Teams router ( — equipos ad-hoc cross-workspace.
    import teams
    app.include_router(teams.router)

    # Admin router ( — operaciones admin (redistribución, etc.).
    import admin
    app.include_router(admin.router)

    # Users router ( — user_preferences GET/PUT /users/me/preferences.
    import users
    app.include_router(users.router)

    # Agents router ( — agent_identity endpoints (Sprint Paridad parcial Opción A).
    import agents
    app.include_router(agents.router)
    app.include_router(agents.router_v1, prefix="/api/v1")

    # Stats router ( — métricas de memorias, grafo, agentes, búsqueda, sistema.
    import stats
    app.include_router(stats.router, prefix="/api/v1")

    # Events router ( — session events + last_seen.
    import events
    app.include_router(events.router, prefix="/api/v1")

    # Onboarding router ( — resumen de proyecto para agente/dashboard.
    import onboarding
    app.include_router(onboarding.router, prefix="/api/v1")

    # Documents router (Task 4.11) — document CRUD + ingestion queue.
    import documents
    app.include_router(documents.router)

    # Org settings router (P1.4.5) — per-project sanitization + retention.
    import org_settings
    app.include_router(org_settings.router)

    # Coverage router (P1.12) — entity coverage model.
    import coverage
    app.include_router(coverage.router)

    # Telemetry router (Fase B.1) — internal-only injection telemetry.
    import telemetry_api
    app.include_router(telemetry_api.router)

    # NOTE: EcoDB metacognition routers (clusters/briefing/foresights/cases/skills/
    # cells) are STRIPPED from KnowTwin — not copied, not wired (P1.1 fork scope).

    # --- Cell config/template + provider routers (retained; curator/verifier
    #     cell types wired in later phases) ---
    import cell_configs
    app.include_router(cell_configs.router, prefix="/api/v1")

    import cell_templates
    app.include_router(cell_templates.router, prefix="/api/v1")

    import providers
    app.include_router(providers.router, prefix="/api/v1")

    return app


# Module-level app para uvicorn — usa el ENVIRONMENT del proceso.
app = create_app()
