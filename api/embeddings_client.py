"""Cliente HTTP del servicio interno de embeddings.

Helper compartido por endpoints que necesitan vectorizar texto:
- POST /memories (memories.py) — guarda con prompt_name='passage'.
- POST /search   (search.py)   — busca con prompt_name='query'.

Coherente con Jina v4: el prefix Query:/Passage: lo gestiona el modelo
internamente via prompt_name. NO inyectar prefijos manualmente.

Refactor deuda #23 (2026-05-08): unifica `_embed_text_for_memory` (memories.py)
y `_embed_query` (search.py) en una sola funcion `embed_text(text, prompt_name)`.

Decision arquitectonica 
estar FUERA del pool DB cuando llame esto. Si embeddings tarda 30s con la GPU
saturada, no queremos bloquear conexiones del pool. El patron trifasico
(validar → libera pool → embed → re-acquire) lo aplica el endpoint llamante.
"""
from __future__ import annotations

import base64
from typing import Literal

import httpx
from fastapi import HTTPException

from settings import EMBEDDINGS_URL, EMBEDDINGS_TIMEOUT, EMBEDDING_DIM


def _format_vec(vec: list) -> str:
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _detect_image_mime(image_base64: str) -> str:
    try:
        header = base64.b64decode(image_base64[:16] + "==")[:8]
    except Exception:
        return "image/png"
    if header[:2] == b"\xff\xd8":
        return "image/jpeg"
    if header[:4] == b"\x89PNG":
        return "image/png"
    if header[:4] == b"RIFF":
        return "image/webp"
    return "image/png"


async def embed_text(
    text: str,
    *,
    prompt_name: Literal["query", "passage"],
) -> str:
    """Llama al servicio embeddings y devuelve el vector como literal pgvector
    `'[1.2,3.4,...]'` listo para `INSERT/UPDATE ... embedding = $1::vector`.

    Args:
        text: contenido a vectorizar (passage) o query a buscar (query).
        prompt_name: 'passage' al guardar memorias, 'query' al buscar.

    Raises:
        HTTPException 503: embeddings caido, response 4xx/5xx, JSON invalido,
        o vector con dim distinta a EMBEDDING_DIM.
    """
    payload = {
        "texts": [text],
        "task": "retrieval",
        "prompt_name": prompt_name,
        "truncate_dim": EMBEDDING_DIM,
    }
    try:
        async with httpx.AsyncClient(timeout=EMBEDDINGS_TIMEOUT) as client:
            r = await client.post(f"{EMBEDDINGS_URL}/embed/text", json=payload)
    except httpx.HTTPError as e:
        raise HTTPException(503, f"embeddings service unavailable: {type(e).__name__}")
    if r.status_code >= 400:
        # No propagamos el body — puede contener detalles internos del servicio.
        raise HTTPException(503, f"embeddings service error {r.status_code}")
    try:
        data = r.json()
        vec = data["embeddings"][0]
    except (KeyError, IndexError, ValueError):
        raise HTTPException(503, "embeddings service returned invalid response")
    if not isinstance(vec, list) or len(vec) != EMBEDDING_DIM:
        raise HTTPException(
            503,
            f"embeddings service returned vector of unexpected shape (expected {EMBEDDING_DIM} dims)",
        )
    # pgvector acepta literal '[1.2,3.4,...]'. repr() de float preserva precision
    # razonable; asyncpg pasa el string tal cual y postgres lo cast a vector.
    # OBS1-NEW (adv-seg #23): si el servicio devuelve elementos no-numericos
    # (null, string), float() lanza ValueError/TypeError y escapa como 500.
    # Lo capturamos para devolver 503 coherente con los demas error paths.
    try:
        return _format_vec(vec)
    except (ValueError, TypeError):
        raise HTTPException(503, "embeddings service returned non-numeric vector elements")


async def embed_image(
    image_base64: str,
) -> str:
    """Llama al servicio embeddings con una imagen y devuelve vector pgvector.

    Args:
        image_base64: imagen codificada en base64 (sin prefijo data URI — se
            añade aquí). PNG, JPEG, WebP soportados por Jina v4.

    Raises:
        HTTPException 503: embeddings caído o respuesta inválida.

    . Jina v4 embede texto e imagen en el mismo
    espacio vectorial 512 dims → cross-modal search gratis.
    """
    mime = _detect_image_mime(image_base64)
    data_uri = f"data:{mime};base64,{image_base64}"
    payload = {
        "images": [data_uri],
        "task": "retrieval",
        "truncate_dim": EMBEDDING_DIM,
    }
    try:
        async with httpx.AsyncClient(timeout=EMBEDDINGS_TIMEOUT) as client:
            r = await client.post(f"{EMBEDDINGS_URL}/embed/image", json=payload)
    except httpx.HTTPError as e:
        raise HTTPException(503, f"embeddings service unavailable: {type(e).__name__}")
    if r.status_code >= 400:
        raise HTTPException(503, f"embeddings service error {r.status_code}")
    try:
        data = r.json()
        vec = data["embeddings"][0]
    except (KeyError, IndexError, ValueError):
        raise HTTPException(503, "embeddings service returned invalid response for image")
    if not isinstance(vec, list) or len(vec) != EMBEDDING_DIM:
        raise HTTPException(
            503,
            f"embeddings image vector unexpected shape (expected {EMBEDDING_DIM} dims)",
        )
    try:
        return _format_vec(vec)
    except (ValueError, TypeError):
        raise HTTPException(503, "embeddings service returned non-numeric vector elements")
