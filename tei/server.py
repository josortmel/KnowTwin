"""
EcoDB embeddings service — Tarea 1.8 + 1.9 plan maestro v3 §7.

Backend dual:
- EMBEDDING_BACKEND=local: PyTorch + bitsandbytes INT8 + Jina v4 (~5-6.5 GB VRAM).
- EMBEDDING_BACKEND=cloud: API Jina (https://api.jina.ai/v1/embeddings).
Cambio manual via env var + restart. Sin mezcla automatica — si local falla, 503.

Endpoints:
- POST /embed/text   → vector(512) por texto, multibatch.
- POST /embed/image  → vector(512) por imagen (URL http(s) o data:image/ base64).
- GET  /health       → liveness check.
- GET  /health/detailed → readiness con VRAM usado/total + cloud_endpoint.

Hardening adv-seg L1+L2+L3 (server.py v0.2.3):
- VS1: JINA_API_URL allowlist (https + api.jina.ai) al startup.
- VS2_CRITICA: /embed/image local rechaza paths locales y file:// (LFI).
- NV1: /embed/image local rechaza http(s):// (SSRF a metadata cloud / red interna).
  URLs solo en EMBEDDING_BACKEND=cloud, donde Jina cloud descarga desde su lado.
- NV2: MAX_IMAGE_REF_LEN cap por imagen (DoS via base64 inflado).
- VS3: MODEL_NAME allowlist + revision pin al SHA cacheado (supply chain).

Hardening adv-code L1:
- BC1: r.json() protegido — non-JSON cloud response → 502 con contexto.
- BC2: items sin 'embedding' field → 502 explicito (no KeyError opaco).
- BC3: asyncio.get_running_loop() (deprecation Python 3.12+).

Sin auth — servicio interno (red Docker privada). Tarea 1.14 lo aisla en
ecodb-net sin exponer puerto 8090 al host.
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import urlparse

import httpx
import psutil
import torch
from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel, Field, field_validator

API_VERSION = "0.2.3"
MODEL_ID = os.environ.get("MODEL_NAME", "jinaai/jina-embeddings-v4")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "512"))
MAX_TEXT_LEN = int(os.environ.get("MAX_TEXT_LEN", "32000"))  # ~8k tokens
MAX_BATCH_TEXT = int(os.environ.get("MAX_BATCH_TEXT", "32"))
MAX_BATCH_IMAGE = int(os.environ.get("MAX_BATCH_IMAGE", "8"))
# NV2 fix (adv-seg) — limite de tamano por imagen para evitar OOM via base64
# inflado. 10 MB de string base64 ~= 7.5 MB de imagen decodificada.
MAX_IMAGE_REF_LEN = int(os.environ.get("MAX_IMAGE_REF_LEN", str(10 * 1024 * 1024)))

# Backend selector — local (PyTorch INT8 con GPU) o cloud (API Jina).
# Cambio manual: admin modifica env var y reinicia. Sin mezcla automatica.
EMBEDDING_BACKEND = os.environ.get("EMBEDDING_BACKEND", "local").lower()
JINA_API_URL = os.environ.get("JINA_API_URL", "https://api.jina.ai/v1/embeddings")
JINA_API_KEY = os.environ.get("JINA_API_KEY", "")
JINA_API_TIMEOUT = float(os.environ.get("JINA_API_TIMEOUT", "30.0"))

if EMBEDDING_BACKEND not in ("local", "cloud"):
    raise RuntimeError(
        f"EMBEDDING_BACKEND debe ser 'local' o 'cloud', got: {EMBEDDING_BACKEND!r}"
    )
if EMBEDDING_BACKEND == "cloud" and not JINA_API_KEY:
    raise RuntimeError("EMBEDDING_BACKEND=cloud requiere JINA_API_KEY env var")

# VS3 fix Tarea 1.14 deuda #18 (adv-seg) — supply chain hardening del modelo HF.
#
# Parte 1 — allowlist de MODEL_NAME: sin esto, MODEL_NAME=evil-user/evil-model con
# trust_remote_code=True ejecutaria codigo arbitrario en startup.
#
# Parte 2 — revision pin: sin esto, cualquier push del owner al repo se descargaria
# como codigo nuevo en startups limpios. El SHA pinado abajo es el snapshot que ya
# auditamos (verify.py PASS, VRAM 4.84 GB, encode_text+image shape (1,512)) el
# 2026-05-08. Si HF actualiza el repo, no se coge hasta cambiar manualmente la env
# var MODEL_REVISION.
_MODEL_ALLOWLIST = {
    "jinaai/jina-embeddings-v4",
    "jinaai/jina-embeddings-v4-vllm-retrieval",  # fallback A documentado en plan v3
}
if EMBEDDING_BACKEND == "local" and MODEL_ID not in _MODEL_ALLOWLIST:
    raise RuntimeError(
        f"MODEL_NAME no permitido en backend local: {MODEL_ID!r}. "
        f"Allowlist: {_MODEL_ALLOWLIST}. Para añadir un modelo nuevo, "
        f"audita su codigo (trust_remote_code=True ejecuta Python del repo HF) "
        f"y actualiza la allowlist."
    )

# Pin al snapshot HF auditado el 2026-05-08 (verify.py PASS).
# Override solo via env var MODEL_REVISION para cambios deliberados — nunca dejar
# que el container coja un commit nuevo silenciosamente.
# NOTA: solo aplica a EMBEDDING_BACKEND=local (lifespan startup llama a
# from_pretrained con revision=). En backend=cloud la API de Jina no expone
# concepto de revision HF — la variable se lee aqui pero queda no-op.
_PINNED_REVISION = "853c867b65b749f3c3c72a06868140d842e04f06"
MODEL_REVISION = os.environ.get("MODEL_REVISION", _PINNED_REVISION)

# VS1 fix (adv-seg) — JINA_API_URL allowlist al startup. Sin esta validacion,
# JINA_API_URL es vector SSRF: apuntar a metadata cloud (169.254.169.254),
# servicios internos, o atacante.com → la JINA_API_KEY se enviaria al destino.
_JINA_HOST_ALLOWLIST = ("api.jina.ai",)
if EMBEDDING_BACKEND == "cloud":
    _parsed = urlparse(JINA_API_URL)
    if _parsed.scheme != "https":
        raise RuntimeError(f"JINA_API_URL debe usar https://, got: {_parsed.scheme!r}")
    if not any(_parsed.hostname == h or (_parsed.hostname or "").endswith("." + h)
               for h in _JINA_HOST_ALLOWLIST):
        raise RuntimeError(
            f"JINA_API_URL host no permitido: {_parsed.hostname!r}. "
            f"Allowlist: {_JINA_HOST_ALLOWLIST}"
        )

# Globals — el modelo se carga UNA vez al lifespan startup (solo backend=local).
_model = None
_health_cache: dict = {"result": None, "checked_at": 0.0}
_health_lock = asyncio.Lock()
_health_logger = logging.getLogger("ecodb.embeddings.health")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Si backend=local, carga el modelo PyTorch INT8 al startup. Si backend=cloud,
    no carga nada — la API de Jina se llama por HTTP en cada request.

    Si la carga local falla, /health responde degraded hasta investigacion."""
    global _model
    if EMBEDDING_BACKEND == "cloud":
        print(f"[startup] backend=cloud → API Jina ({JINA_API_URL}). No se carga modelo local.", flush=True)
        yield
        return

    print(f"[startup] backend=local → cargando modelo {MODEL_ID} con bitsandbytes INT8...", flush=True)
    t0 = time.time()
    try:
        from transformers import AutoModel, BitsAndBytesConfig
        config = BitsAndBytesConfig(load_in_8bit=True)
        _model = AutoModel.from_pretrained(
            MODEL_ID,
            revision=MODEL_REVISION,
            trust_remote_code=True,
            quantization_config=config,
            device_map="auto",
        )
        print(f"[startup] modelo cargado en {time.time() - t0:.1f}s", flush=True)
        if torch.cuda.is_available():
            mem_used_mib = torch.cuda.memory_allocated() // (1024 ** 2)
            print(f"[startup] VRAM usada tras carga: {mem_used_mib} MiB", flush=True)
    except Exception as e:
        print(f"[startup] FALLO carga del modelo: {e}", flush=True)
        _model = None
    yield
    # Shutdown — liberar VRAM
    _model = None
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


app = FastAPI(
    title="EcoDB Embeddings",
    version=API_VERSION,
    lifespan=lifespan,
    docs_url="/docs",  # interno, sin auth — sin riesgo de exposicion publica
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class EmbedTextRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=MAX_BATCH_TEXT)
    task: str = Field("retrieval", pattern="^(retrieval|text-matching|code)$")
    prompt_name: str = Field("passage", pattern="^(query|passage)$")
    truncate_dim: int = Field(EMBEDDING_DIM, ge=64, le=2048)

    @field_validator("texts")
    @classmethod
    def _validate_texts(cls, v: list[str]) -> list[str]:
        for t in v:
            if not t:
                raise ValueError("text cannot be empty")
            if len(t) > MAX_TEXT_LEN:
                raise ValueError(f"text exceeds max length {MAX_TEXT_LEN}")
            if "\x00" in t:
                raise ValueError("text cannot contain null bytes")
        return v


class EmbedImageRequest(BaseModel):
    images: list[str] = Field(..., min_length=1, max_length=MAX_BATCH_IMAGE,
                              description="Cada imagen como data URI base64 (local) o URL http(s)/data URI (cloud)")
    task: str = Field("retrieval", pattern="^(retrieval|text-matching|code)$")
    truncate_dim: int = Field(EMBEDDING_DIM, ge=64, le=2048)

    @field_validator("images")
    @classmethod
    def _validate_images(cls, v: list[str]) -> list[str]:
        # NV2 fix (adv-seg) — bound por item para evitar DoS via base64 inflado.
        # Sin esto, un cliente puede mandar varios MB que pasan Pydantic, llegan
        # al handler, b64decode los expande, PIL los abre → OOM del container.
        for img in v:
            if not img:
                raise ValueError("image reference cannot be empty")
            if len(img) > MAX_IMAGE_REF_LEN:
                raise ValueError(
                    f"image reference exceeds max length {MAX_IMAGE_REF_LEN} chars"
                )
        return v


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
    model: str
    dimensions: int
    count: int
    duration_ms: float


class HealthResponse(BaseModel):
    status: str
    backend: str
    quantization: str
    model_loaded: bool


class HealthDetailedResponse(HealthResponse):
    vram_used_mib: Optional[int]
    vram_total_mib: Optional[int]
    vram_free_mib: Optional[int]
    cpu_percent: float
    ram_percent: float
    cloud_endpoint: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    from fastapi.responses import JSONResponse
    if EMBEDDING_BACKEND == "cloud":
        return {"status": "ok", "backend": "cloud", "model_functional": True}
    if _model is None:
        return JSONResponse({"status": "unhealthy", "error": "model not loaded"}, status_code=503)
    now = time.time()
    # Fast path: cache hit (outside lock — avoids lock contention on warm path)
    if _health_cache["result"] is not None and now - _health_cache["checked_at"] < 60:
        cached = _health_cache["result"]
        if cached["ok"]:
            return {"status": "ok", "backend": "local", "model_functional": True}
        return JSONResponse({"status": "unhealthy", "error": cached["error"]}, status_code=503)
    # Cache miss: acquire lock + double-check inside (BC1/4a-4 stampede guard)
    async with _health_lock:
        now = time.time()
        if _health_cache["result"] is not None and now - _health_cache["checked_at"] < 60:
            cached = _health_cache["result"]
            if cached["ok"]:
                return {"status": "ok", "backend": "local", "model_functional": True}
            return JSONResponse({"status": "unhealthy", "error": cached["error"]}, status_code=503)
        # BC2: capture model ref — avoids TOCTOU if _model=None during shutdown
        model_ref = _model
        if model_ref is None:
            return JSONResponse({"status": "unhealthy", "error": "model not loaded"}, status_code=503)
        try:
            await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: model_ref.encode_text(
                    ["health check"], task="retrieval", prompt_name="query", truncate_dim=512
                ),
            )
            _health_cache.update({"result": {"ok": True}, "checked_at": now})
            return {"status": "ok", "backend": "local", "model_functional": True}
        except Exception as e:
            _health_logger.warning("health check encode_text failed: %s", e)
            _health_cache.update({"result": {"ok": False, "error": type(e).__name__}, "checked_at": now})
            return JSONResponse({"status": "unhealthy", "error": type(e).__name__}, status_code=503)


@app.get("/health/detailed", response_model=HealthDetailedResponse)
async def health_detailed() -> HealthDetailedResponse:
    vram_used = vram_total = vram_free = None
    if EMBEDDING_BACKEND == "local" and torch.cuda.is_available():
        vram_used = torch.cuda.memory_allocated() // (1024 ** 2)
        vram_total = torch.cuda.get_device_properties(0).total_memory // (1024 ** 2)
        vram_free = vram_total - vram_used
    is_cloud = EMBEDDING_BACKEND == "cloud"
    return HealthDetailedResponse(
        status="ok" if (is_cloud or _model is not None) else "degraded",
        backend=EMBEDDING_BACKEND,
        quantization="n/a" if is_cloud else "int8",
        model_loaded=is_cloud or _model is not None,
        vram_used_mib=vram_used,
        vram_total_mib=vram_total,
        vram_free_mib=vram_free,
        cpu_percent=psutil.cpu_percent(interval=None),
        ram_percent=psutil.virtual_memory().percent,
        cloud_endpoint=JINA_API_URL if is_cloud else None,
    )


# ---------------------------------------------------------------------------
# Cloud backend (API Jina) — Tarea 1.9
# ---------------------------------------------------------------------------

def _map_task_for_cloud(task: str, prompt_name: str | None) -> str:
    """Mapping local→cloud: la API de Jina usa task con dot notation.

    local task='retrieval' + prompt_name='query'   → cloud 'retrieval.query'
    local task='retrieval' + prompt_name='passage' → cloud 'retrieval.passage'
    local task='text-matching'                     → cloud 'text-matching'
    local task='code'                              → cloud 'code.query'
    """
    if task == "retrieval":
        return f"retrieval.{prompt_name or 'query'}"
    if task == "code":
        return "code.query"
    return task


async def _post_jina_cloud(payload: dict) -> dict:
    headers = {"Authorization": f"Bearer {JINA_API_KEY}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=JINA_API_TIMEOUT) as client:
        try:
            r = await client.post(JINA_API_URL, json=payload, headers=headers)
        except httpx.HTTPError as e:
            raise HTTPException(503, f"cloud connection failed: {type(e).__name__}")
    if r.status_code >= 400:
        # Status code SI lo propagamos. Body NO — VS4 (adv-seg): podria contener
        # la key parcial o, si VS1 no protegiese, el body de un servicio interno.
        raise HTTPException(502, f"cloud upstream error {r.status_code}")
    # BC1 fix (adv-code) — r.json() puede fallar si Jina (o un proxy/CDN
    # intermedio) devuelve 200 con HTML/texto plano (mantenimiento, error page).
    try:
        return r.json()
    except Exception:
        raise HTTPException(502, f"cloud returned non-JSON response (status {r.status_code})")


def _extract_embeddings(data: dict, expected_count: int) -> list[list[float]]:
    """BC2 fix (adv-code) — extrae embeddings con validacion explicita.
    Si la API Jina devuelve un item sin clave 'embedding' (ej. malformado),
    lanzamos 502 con contexto en vez de KeyError opaco que se traduce a 500.
    """
    items = data.get("data", [])
    embeddings: list[list[float]] = []
    for i, item in enumerate(items):
        emb = item.get("embedding") if isinstance(item, dict) else None
        if emb is None:
            raise HTTPException(502, f"cloud response item {i} missing 'embedding' field")
        embeddings.append(emb)
    if len(embeddings) != expected_count:
        raise HTTPException(502, f"cloud returned {len(embeddings)} vectors, expected {expected_count}")
    return embeddings


async def _embed_text_cloud(body: EmbedTextRequest, t0: float) -> EmbedResponse:
    payload = {
        "model": MODEL_ID.split("/")[-1],
        "task": _map_task_for_cloud(body.task, body.prompt_name),
        "dimensions": body.truncate_dim,
        "embedding_type": "float",
        "input": [{"text": t} for t in body.texts],
    }
    data = await _post_jina_cloud(payload)
    embeddings = _extract_embeddings(data, len(body.texts))
    return EmbedResponse(
        embeddings=embeddings,
        model=MODEL_ID.split("/")[-1],
        dimensions=body.truncate_dim,
        count=len(embeddings),
        duration_ms=round((time.time() - t0) * 1000, 2),
    )


async def _embed_image_cloud(body: EmbedImageRequest, t0: float) -> EmbedResponse:
    # Jina cloud acepta URL http(s) o data URI base64 directamente. Paths locales
    # del filesystem del API NO funcionan en cloud — el servicio remoto no tiene
    # acceso. Rechazamos explicitamente con 422.
    inputs = []
    for img_ref in body.images:
        if img_ref.startswith(("http://", "https://")) or img_ref.lower().startswith("data:image/"):
            inputs.append({"image": img_ref})
        else:
            raise HTTPException(
                422,
                "image reference must be http(s) URL or data:image/ base64 URI",
            )
    payload = {
        "model": MODEL_ID.split("/")[-1],
        "task": _map_task_for_cloud(body.task, None),
        "dimensions": body.truncate_dim,
        "embedding_type": "float",
        "input": inputs,
    }
    data = await _post_jina_cloud(payload)
    embeddings = _extract_embeddings(data, len(body.images))
    return EmbedResponse(
        embeddings=embeddings,
        model=MODEL_ID.split("/")[-1],
        dimensions=body.truncate_dim,
        count=len(embeddings),
        duration_ms=round((time.time() - t0) * 1000, 2),
    )


# ---------------------------------------------------------------------------
# Embedding endpoints
# ---------------------------------------------------------------------------

@app.post("/embed/text", response_model=EmbedResponse)
async def embed_text(body: EmbedTextRequest) -> EmbedResponse:
    t0 = time.time()
    if EMBEDDING_BACKEND == "cloud":
        return await _embed_text_cloud(body, t0)
    if _model is None:
        raise HTTPException(503, "model not loaded")
    try:
        # encode_text es bloqueante (PyTorch GPU). Lo ejecutamos en thread pool
        # para no bloquear el event loop del API.
        embeddings = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: _model.encode_text(
                texts=body.texts,
                task=body.task,
                prompt_name=body.prompt_name,
                truncate_dim=body.truncate_dim,
            ),
        )
    except Exception as e:
        raise HTTPException(500, f"embedding failed: {type(e).__name__}")

    if hasattr(embeddings, "tolist"):
        result_list = embeddings.tolist()
    else:
        result_list = [list(emb) for emb in embeddings]

    return EmbedResponse(
        embeddings=result_list,
        model=MODEL_ID.split("/")[-1],
        dimensions=body.truncate_dim,
        count=len(result_list),
        duration_ms=round((time.time() - t0) * 1000, 2),
    )


@app.post("/embed/image", response_model=EmbedResponse)
async def embed_image(body: EmbedImageRequest) -> EmbedResponse:
    t0 = time.time()
    if EMBEDDING_BACKEND == "cloud":
        return await _embed_image_cloud(body, t0)
    if _model is None:
        raise HTTPException(503, "model not loaded")
    # VS2_CRITICA + NV1 fix (adv-seg) — solo data:image/ base64 en local.
    # Rechazamos paths del filesystem (LFI), file://, y URLs http(s) (SSRF).
    # Razon NV1: Jina v4 baja URLs internamente desde el container, lo que
    # permite SSRF a metadata services (169.254.169.254 en AWS/GCP/Azure) o a
    # servicios privados de la red. Para URLs, usar EMBEDDING_BACKEND=cloud
    # (Jina cloud descarga desde su infraestructura, no desde nuestro container).
    images_resolved = []
    for img_ref in body.images:
        if img_ref.lower().startswith("data:image/"):
            try:
                _, payload = img_ref.split(",", 1)
                raw = base64.b64decode(payload)
                pil = Image.open(io.BytesIO(raw))
                images_resolved.append(pil)
            except Exception:
                raise HTTPException(422, "invalid base64 image")
        else:
            raise HTTPException(
                422,
                "image must be data:image/ base64 URI in local backend; use EMBEDDING_BACKEND=cloud for http(s) URLs"
            )

    try:
        embeddings = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: _model.encode_image(
                images=images_resolved,
                task=body.task,
                truncate_dim=body.truncate_dim,
            ),
        )
    except Exception as e:
        raise HTTPException(500, f"embedding failed: {type(e).__name__}")

    if hasattr(embeddings, "tolist"):
        result_list = embeddings.tolist()
    else:
        result_list = [list(emb) for emb in embeddings]

    return EmbedResponse(
        embeddings=result_list,
        model=MODEL_ID.split("/")[-1],
        dimensions=body.truncate_dim,
        count=len(result_list),
        duration_ms=round((time.time() - t0) * 1000, 2),
    )
