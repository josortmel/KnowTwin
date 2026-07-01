"""Central API configuration. All values come from environment variables with reasonable defaults.

Variables:
- ENVIRONMENT          : "development" or "production" (default development).
- DATABASE_URL         : async postgres DSN (default localhost:5435 ecodb test).
- JWT_SECRET           : HMAC secret for signing JWTs (default DEV ONLY).
- JWT_TTL_SECONDS      : JWT lifetime, default 3600 (1 hour).
- API_KEY_PEPPER       : pepper for hashing API keys (default DEV ONLY).
- CORS_ORIGINS         : comma-separated, default http://localhost:8080,http://localhost:8091.
- API_VERSION          : external version string, default 0.9.0.

NEVER use the JWT_SECRET / API_KEY_PEPPER defaults in production.
The Docker image will FAIL to start if ENVIRONMENT=production and secrets
are still set to their development defaults.
"""
import os

ENVIRONMENT = os.environ.get("ENVIRONMENT", "development").lower()
IS_PRODUCTION = ENVIRONMENT == "production"
IS_DEVELOPMENT = ENVIRONMENT == "development"

API_VERSION = os.environ.get("API_VERSION", "0.1.0")
SCHEMA_VERSION = "0.1.0"  # KnowTwin baseline (real schema lands in P1.2)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://knowtwin:knowtwin_test_pass@localhost:5436/knowtwin",
)

# JWT
_JWT_SECRET_DEV = "DEV_ONLY_CHANGE_IN_PRODUCTION_VIA_ENV_VAR"
JWT_SECRET = os.environ.get("JWT_SECRET", _JWT_SECRET_DEV)
JWT_ALGORITHM = "HS256"
JWT_TTL_SECONDS = int(os.environ.get("JWT_TTL_SECONDS", "3600"))  # 1h default

# API keys
_API_KEY_PEPPER_DEV = "DEV_ONLY_PEPPER_CHANGE_IN_PRODUCTION_VIA_ENV_VAR"
API_KEY_PEPPER = os.environ.get("API_KEY_PEPPER", _API_KEY_PEPPER_DEV)
# VS2: known dev / docker-compose fallback secret literals. Rejected fail-closed
# in production so a stack booted with the compose defaults can't run exposed.
_KNOWN_DEV_DEFAULTS = frozenset({
    _JWT_SECRET_DEV, _API_KEY_PEPPER_DEV,
    "dev_only_change_me_jwt", "dev_only_change_me_pepper", "knowtwin_test_pass",
})
API_KEY_PREFIX = "ecodb_"  # prefijo visible para identificar API keys de ecodb

# CORS — restrictive policy, no wildcard, no credentials.
_default_origins = "http://localhost:8080,http://localhost:8091"
CORS_ORIGINS = [
    o.strip() for o in os.environ.get("CORS_ORIGINS", _default_origins).split(",") if o.strip()
]

# Embeddings service — Jina v4 INT8 running in a separate container.
# Default: localhost:8090 for tests; in docker-compose it will be
# http://embeddings:8090 inside the ecodb-net network.
#
# EMBEDDINGS_TIMEOUT is per httpx phase (connect, read), NOT total — worst
# case is ~2x this value. For an internal GPU-warm service, 30s per phase is conservative.
EMBEDDINGS_URL = os.environ.get("EMBEDDINGS_URL", "http://localhost:8090")
EMBEDDINGS_TIMEOUT = float(os.environ.get("EMBEDDINGS_TIMEOUT", "30.0"))

# DB pool (db.py)
DB_POOL_MIN = int(os.environ.get("DB_POOL_MIN", "2"))
DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "10"))
DB_COMMAND_TIMEOUT = int(os.environ.get("DB_COMMAND_TIMEOUT", "10"))

# Rate limiting (rate_limit.py)
RATE_LIMIT_SEARCH = int(os.environ.get("RATE_LIMIT_SEARCH", "60"))
RATE_LIMIT_DEFAULT = int(os.environ.get("RATE_LIMIT_DEFAULT", "120"))
RATE_LIMIT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", "60"))

# Circuit breaker for embeddings (worker.py)
CB_THRESHOLD = int(os.environ.get("CB_THRESHOLD", "3"))
CB_WINDOW = int(os.environ.get("CB_WINDOW", "60"))
CB_COOLDOWN = int(os.environ.get("CB_COOLDOWN", "30"))
EMBEDDING_DIM = 512  # must match embeddings service (Matryoshka truncate). SQL declares vector(512).

# EMBEDDINGS_URL must point to an internal host. In production, public/metadata URLs
# are rejected to prevent content exfiltration via SSRF.
# Docker network uses HTTP (not HTTPS) — allowlist is by hostname, not scheme.
_EMBEDDINGS_HOST_ALLOWLIST = ("knowtwin-tei", "embeddings", "localhost", "127.0.0.1", "host.docker.internal")
_LLM_HOST_ALLOWLIST = ("llm", "localhost", "127.0.0.1", "host.docker.internal")


def validate_production_secrets() -> None:
    """Llamar al startup del API. Falla si ENVIRONMENT=production y los secretos
    siguen en sus valores de desarrollo. NO se ejecuta en import — eso bloqueaba
    tests y smoke checks que cargan settings con env por defecto."""
    if not IS_PRODUCTION:
        return
    # Empty strings and short secrets are insecure. docker compose substitutes ""
    # for undefined variables — without these checks the API would start with
    # JWT_SECRET="" → any client could forge tokens with HMAC-SHA256("", payload).
    # 16 chars minimum; recommended 32+ bytes random hex (~64 chars).
    if not JWT_SECRET or len(JWT_SECRET) < 16 or JWT_SECRET in _KNOWN_DEV_DEFAULTS:
        raise RuntimeError(
            "JWT_SECRET vacio, demasiado corto (<16 chars) o con valor de desarrollo "
            "en ENVIRONMENT=production. Configura JWT_SECRET (random 32+ bytes) "
            "via env var antes de arrancar. Generar con: openssl rand -hex 32"
        )
    if not API_KEY_PEPPER or len(API_KEY_PEPPER) < 16 or API_KEY_PEPPER in _KNOWN_DEV_DEFAULTS:
        raise RuntimeError(
            "API_KEY_PEPPER vacio, demasiado corto (<16 chars) o con valor de desarrollo "
            "en ENVIRONMENT=production. Configura API_KEY_PEPPER (random 32+ bytes) "
            "via env var antes de arrancar. Generar con: openssl rand -hex 32"
        )
    # Never accept wildcard CORS in production. If an operator sets CORS_ORIGINS=*
    # to "fix dev", block startup in prod to prevent CSRF cross-origin attacks.
    if "*" in CORS_ORIGINS:
        raise RuntimeError(
            "CORS_ORIGINS contiene '*' en ENVIRONMENT=production. "
            "Define orígenes explícitos por seguridad (CSRF cross-origin)."
        )
    # EMBEDDINGS_URL must not point to an external host in production —
    # SSRF vector that could exfiltrate memory content.
    from urllib.parse import urlparse
    parsed = urlparse(EMBEDDINGS_URL)
    if not parsed.hostname or parsed.hostname not in _EMBEDDINGS_HOST_ALLOWLIST:
        raise RuntimeError(
            f"EMBEDDINGS_URL host no permitido en production: {parsed.hostname!r}. "
            f"Allowlist: {_EMBEDDINGS_HOST_ALLOWLIST}. "
            f"Si necesitas otro host (ej. red Docker custom), añadelo a la allowlist."
        )
    if ECODB_LLM_PROVIDER == "local":
        parsed_llm = urlparse(LLAMA_CPP_URL)
        if not parsed_llm.hostname or parsed_llm.hostname not in _LLM_HOST_ALLOWLIST:
            raise RuntimeError(
                f"LLAMA_CPP_URL host not allowed in production: {parsed_llm.hostname!r}. "
                f"Allowlist: {_LLM_HOST_ALLOWLIST}"
            )
    if ECODB_LLM_PROVIDER == "deepseek":
        parsed_ds = urlparse(DEEPSEEK_URL)
        if not parsed_ds.hostname or not parsed_ds.hostname.endswith("deepseek.com"):
            raise RuntimeError(
                f"DEEPSEEK_URL host not allowed in production: {parsed_ds.hostname!r}. "
                f"Must end with deepseek.com"
            )
    import crypto
    if not crypto.encryption_key_ok():
        raise RuntimeError(
            "ENCRYPTION_KEY not set or invalid in ENVIRONMENT=production. "
            "Required to encrypt LLM provider keys. Generate with: "
            "python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    _broadcast_secret = os.environ.get("INTERNAL_BROADCAST_SECRET", "")
    if not _broadcast_secret or len(_broadcast_secret) < 16:
        import logging
        logging.getLogger("ecodb.security").warning(
            "INTERNAL_BROADCAST_SECRET empty or too short in production. "
            "Worker SSE events will be silently dropped. "
            "Generate with: openssl rand -hex 32"
        )


# Feature flags — all false by default. Activate one at a time
# after running golden set evaluation (eval/golden_set.py) before/after.
def _env_bool(key: str, default: bool = False) -> bool:
    return os.environ.get(key, str(default)).lower() in ("true", "1", "yes", "on")

ENABLE_BM25 = _env_bool("ENABLE_BM25")
ENABLE_AUTO_LINK = _env_bool("ENABLE_AUTO_LINK")
ENABLE_WEIGHT_DYNAMIC = _env_bool("ENABLE_WEIGHT_DYNAMIC")
ENABLE_TRUST_TIERS = _env_bool("ENABLE_TRUST_TIERS")
ENABLE_STOP_ENTITIES_DYNAMIC = _env_bool("ENABLE_STOP_ENTITIES_DYNAMIC")
ENABLE_TENSION_DETECTION = _env_bool("ENABLE_TENSION_DETECTION")
ENABLE_CONTEXT_INJECTION = _env_bool("ENABLE_CONTEXT_INJECTION")
ENABLE_BM25_EXPANSION = _env_bool("ENABLE_BM25_EXPANSION")
ENABLE_HYDE = _env_bool("ENABLE_HYDE")
ENABLE_POST_HOC_CLASSIFIER = _env_bool("ENABLE_POST_HOC_CLASSIFIER")
ENABLE_LLM_TELEMETRY = _env_bool("ENABLE_LLM_TELEMETRY")

# Weight multiplicative floor: weight signal is attenuated by semantic relevance.
# weight_term = w["weight"] * memory_weight * (WEIGHT_ALPHA + (1-WEIGHT_ALPHA) * semantic_score)
# At WEIGHT_ALPHA=0.25: a decision (weight=0.9) with low semantic (0.2) → 0.9 × 0.40 = 0.36 instead of 0.9.
WEIGHT_ALPHA = float(os.environ.get("WEIGHT_ALPHA", "0.30"))

COOCCURRENCE_THRESHOLD = int(os.environ.get("COOCCURRENCE_THRESHOLD", "3"))

NER_SERVICE_URL = os.environ.get("NER_SERVICE_URL", "http://knowtwin-ner:8091")

GAMR_WEIGHTS_BM25: dict[str, dict[str, float]] = {
    "factual":    {"semantic": 0.70, "graph": 0.05, "weight": 0.07, "freshness": 0.08, "bm25": 0.10},
    "historical": {"semantic": 0.70, "graph": 0.05, "weight": 0.10, "freshness": 0.02, "bm25": 0.10},
    "analytical": {"semantic": 0.70, "graph": 0.05, "weight": 0.10, "freshness": 0.05, "bm25": 0.10},
    "contextual": {"semantic": 0.70, "graph": 0.05, "weight": 0.07, "freshness": 0.08, "bm25": 0.10},
}

RERANK_FETCH_K = int(os.environ.get("RERANK_FETCH_K", "50"))
MAX_FETCH_K = int(os.environ.get("MAX_FETCH_K", "200"))

RERANKER_MODEL_ALLOWLIST = {
    "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "cross-encoder/ms-marco-MiniLM-L-12-v2",
    "BAAI/bge-reranker-base",
}

# LLM provider for HyDE, telemetry, classifier (Adendum A, 2026-05-14)
ECODB_LLM_PROVIDER = os.environ.get("ECODB_LLM_PROVIDER", "off")  # AU1: default off (no llama/cell provider wired)
LLAMA_CPP_URL = os.environ.get("LLAMA_CPP_URL", "http://llm:8080")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
HAIKU_MODEL = os.environ.get("HAIKU_MODEL", "claude-haiku-4-5-20251001")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_URL = os.environ.get("DEEPSEEK_URL", "https://api.deepseek.com")
MAX_LLM_TOKENS = int(os.environ.get("MAX_LLM_TOKENS", "512"))

# --- Cell worker configuration ---
CELL_LLM_PROVIDER = os.environ.get("CELL_LLM_PROVIDER", "deepseek")
CELL_LLM_URL = os.environ.get("CELL_LLM_URL", "https://api.deepseek.com")
CELL_LLM_KEY = os.environ.get("CELL_LLM_KEY", "")
CELL_LLM_MODEL = os.environ.get("CELL_LLM_MODEL", "deepseek-chat")

# DC1: EcoDB consolidation/foresight/skill-distillation params REMOVED — those
# metacognition cells are not part of KnowTwin (clusters table dropped). Curator/
# Verifier cell config lives in the DB (cell_task_configs), not here.
