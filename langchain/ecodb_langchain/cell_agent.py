"""LangChain engine for the EcoDB cell worker (metacognition).

The cell worker (api/cell_worker.py) does deterministic clustering (numpy/scipy)
and governed DB writes (ecodb_cell role). Its ONLY LLM dependency is a single
function: ``_llm_call(system, user) -> json_string``. Every cell job
(consolidation narration, fractal monthly/quarterly/yearly, foresight temporal
extraction, case structuring, skill distillation, identity tensions) funnels
through it.

This module provides a model-agnostic LangChain replacement for exactly that
seam — so the cell worker's reasoning runs on LangChain (any model) instead of a
hand-rolled httpx call to DeepSeek, WITHOUT touching the clustering math, the
prompts, or the authorship-boundary writes. That is the faithful "cell worker on
LangChain": the deterministic pipeline stays a pipeline (forcing it into a
tool-calling agent loop would be theater), the reasoning becomes LangChain.

Wiring in api/cell_worker.py — replace the body of _llm_call:

    from ecodb_langchain.cell_agent import make_cell_llm, acell_llm_call
    _CELL_LLM = make_cell_llm()  # built once at import

    async def _llm_call(system_prompt: str, user_prompt: str) -> str:
        return await acell_llm_call(system_prompt, user_prompt, llm=_CELL_LLM)

Nothing else in cell_worker.py changes. Same prompts, same JSON contracts, same
temperature/max_tokens, same retry wrapper (_llm_retry) around it.
"""

from __future__ import annotations

import os
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage


def make_cell_llm(
    *,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 16384,
    json_mode: bool = True,
) -> BaseChatModel:
    """Build the cell worker's chat model, defaulting to DeepSeek (the worker's
    current backend) with JSON response mode — same params as the old _llm_call.
    Model-agnostic: pass model/api_key/base_url for any OpenAI-compatible LLM,
    or build a different BaseChatModel yourself and hand it to acell_llm_call.
    """
    from langchain_openai import ChatOpenAI

    model = model or os.environ.get("CELL_LLM_MODEL", "deepseek-chat")
    api_key = api_key or os.environ.get("CELL_LLM_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise ValueError("CELL_LLM_KEY or DEEPSEEK_API_KEY must be set (env var or pass api_key=)")
    base_url = base_url or os.environ.get("CELL_LLM_URL", "https://api.deepseek.com")
    model_kwargs = {}
    if json_mode:
        model_kwargs["response_format"] = {"type": "json_object"}
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=float(os.environ.get("CELL_LLM_TIMEOUT", "60")),
        model_kwargs=model_kwargs,
    )


_DEFAULT_CELL_LLM: Optional[BaseChatModel] = None


async def acell_llm_call(
    system_prompt: str,
    user_prompt: str,
    *,
    llm: Optional[BaseChatModel] = None,
) -> str:
    """Drop-in replacement for cell_worker._llm_call.

    Sends system + user messages to a LangChain chat model and returns the raw
    text content (the JSON string the cell expects). The cell worker's existing
    json.loads(...) and _llm_retry(...) wrap this unchanged.
    """
    global _DEFAULT_CELL_LLM
    if llm is None:
        if _DEFAULT_CELL_LLM is None:
            _DEFAULT_CELL_LLM = make_cell_llm()
        llm = _DEFAULT_CELL_LLM
    resp = await llm.ainvoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    content = resp.content
    if isinstance(content, list):
        # Some providers return content blocks; concatenate the text parts.
        content = "".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    return content
