"""Telemetry endpoints — auth-gated (VS1)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import settings
from auth import get_current_user
from db import get_pool
from telemetry import compute_use_score_llm, evaluate_injection, record_injection

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


class RecordRequest(BaseModel):
    injection_id: str
    memory_ids: list[str]
    scores: Optional[list[float]] = None
    agent_identifier: Optional[str] = None
    prompt_hash: Optional[str] = None


class EvaluateRequest(BaseModel):
    injection_id: str
    use_score: float
    novel_entities: Optional[list[str]] = None
    injection_text: Optional[str] = None
    response_text: Optional[str] = None


@router.post("/record")
async def telemetry_record(body: RecordRequest, actor: dict = Depends(get_current_user)):
    pool = await get_pool()
    await record_injection(
        pool,
        injection_id=body.injection_id,
        memory_ids=body.memory_ids,
        scores=body.scores or [],
        agent_identifier=body.agent_identifier,
        prompt_text=body.prompt_hash,
    )
    return {"ok": True}


@router.post("/evaluate")
async def telemetry_evaluate(body: EvaluateRequest, actor: dict = Depends(get_current_user)):
    pool = await get_pool()
    use_score = body.use_score
    novel_entities = body.novel_entities or []

    if (settings.ENABLE_LLM_TELEMETRY
            and body.injection_text
            and body.response_text):
        llm_result = await compute_use_score_llm(body.injection_text, body.response_text)
        if llm_result and isinstance(llm_result.get("score"), (int, float)):
            use_score = max(0.0, min(1.0, float(llm_result["score"])))

    await evaluate_injection(
        pool,
        injection_id=body.injection_id,
        use_score=use_score,
        novel_entities=novel_entities,
    )
    return {"ok": True}
