"""Cross-encoder reranker for GAMR Etapa 9.

Loads a cross-encoder model at import time. If the model fails to load
(missing cache, corrupt download), the module exposes rerank() as a
no-op that returns results unchanged + logs WARNING.

Security: trust_remote_code=False, revision pinned to specific SHA.
Must run locally — never call external reranking APIs.
"""
import logging
import os

log = logging.getLogger("ecodb.reranker")

RERANKER_MODEL = os.environ.get("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RERANKER_REVISION = os.environ.get("RERANKER_REVISION", "")  # SHA pin — set in docker-compose
RERANKER_ENABLED = os.environ.get("RERANKER_ENABLED", "true").lower() == "true"

_model = None
_available = False


def _load_model():
    """Attempt to load cross-encoder. Fail-closed: if load fails, reranking disabled with WARNING."""
    global _model, _available
    if not RERANKER_ENABLED:
        log.info("Reranker disabled by RERANKER_ENABLED=false")
        return
    from settings import RERANKER_MODEL_ALLOWLIST
    if RERANKER_MODEL not in RERANKER_MODEL_ALLOWLIST:
        log.error("RERANKER_MODEL %r not in allowlist — refusing to load", RERANKER_MODEL)
        return
    if not RERANKER_REVISION:
        log.error("RERANKER_REVISION must be set — pin model SHA for supply chain safety")
        return
    try:
        from sentence_transformers import CrossEncoder
        kwargs = {
            "trust_remote_code": False,
            "revision": RERANKER_REVISION,
            "model_kwargs": {"use_safetensors": True},
        }
        _model = CrossEncoder(RERANKER_MODEL, **kwargs)
        _available = True
        log.info("Reranker loaded: %s (revision=%s)", RERANKER_MODEL, RERANKER_REVISION)
    except Exception as e:
        log.warning("Reranker unavailable — serving without reranking: %s", e)
        _model = None
        _available = False


_load_model()


def is_available() -> bool:
    return _available


def rerank(query: str, results: list[dict], top_k: int) -> list[dict]:
    """Rerank results by cross-encoder score. Returns top_k results in new order.

    If reranker unavailable, returns results[:top_k] unchanged (graceful degradation).
    """
    if not _available or not results:
        return results[:top_k]

    pairs = [(query, (r.get("content") or "")[:2000]) for r in results]
    try:
        scores = _model.predict(pairs)
    except Exception as e:
        log.warning("Reranker inference failed, returning original order: %s", e)
        return results[:top_k]

    for r, score in zip(results, scores, strict=True):
        r["reranker_score"] = float(score)

    reranked = sorted(results, key=lambda r: r.get("reranker_score", -999), reverse=True)
    return reranked[:top_k]
