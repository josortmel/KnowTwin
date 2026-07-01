"""GLiNER NER microservice — lightweight HTTP API."""
import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field

log = logging.getLogger("ecodb.ner")

_model = None


@asynccontextmanager
async def lifespan(app):
    global _model
    log.info("Loading GLiNER model...")
    t0 = time.time()
    from gliner import GLiNER
    loop = asyncio.get_running_loop()
    _model = await loop.run_in_executor(None, GLiNER.from_pretrained, "urchade/gliner_multi-v2.1")
    log.info("GLiNER loaded in %.1fs", time.time() - t0)
    yield
    _model = None


app = FastAPI(lifespan=lifespan)


class NERRequest(BaseModel):
    text: str = Field(..., max_length=32000)
    labels: list[str] = Field(..., max_length=20)
    threshold: float = Field(0.7, ge=0.0, le=1.0)


@app.post("/extract")
async def extract(req: NERRequest):
    loop = asyncio.get_running_loop()
    entities = await loop.run_in_executor(
        None, lambda: _model.predict_entities(req.text, req.labels, threshold=req.threshold)
    )
    return [
        {
            "text": e["text"],
            "label": e["label"],
            "start": e["start"],
            "end": e["end"],
            "score": round(e["score"], 4),
        }
        for e in entities
    ]


@app.get("/health")
async def health():
    return {"status": "ok" if _model is not None else "loading"}
