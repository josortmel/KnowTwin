"""LLM provider abstraction — multi-backend (local llama.cpp / Haiku API / DeepSeek API).

All call sites use `get_llm_provider().generate(prompt, max_tokens, temperature)`.
Provider selected by ECODB_LLM_PROVIDER env var. If provider is unavailable,
generate() returns None — callers treat this as feature-off (same as flag disabled).
"""
import logging
from abc import ABC, abstractmethod

import httpx

import settings

log = logging.getLogger("ecodb.llm")

class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, max_tokens: int = 256,
                       temperature: float = 0.3) -> str | None:
        """Generate text from prompt. Callers MUST sanitize user content
        in the prompt to prevent prompt injection (VS_NEW2). Never pass
        raw user-stored memories without defensive system prompt."""
        ...

    @abstractmethod
    async def available(self) -> bool: ...

    async def aclose(self) -> None:
        pass


class LlamaCppProvider(LLMProvider):
    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=60.0)

    async def generate(self, prompt: str, max_tokens: int = 256,
                       temperature: float = 0.3) -> str | None:
        max_tokens = min(max_tokens, settings.MAX_LLM_TOKENS)
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        try:
            r = await self._client.post(f"{self.url}/v1/chat/completions", json=payload)
            r.raise_for_status()
            data = r.json()
            choices = data.get("choices", [])
            if not choices:
                log.warning("LlamaCpp returned empty choices")
                return None
            return choices[0].get("message", {}).get("content")
        except Exception as e:
            log.warning("LlamaCpp generate failed: %s", type(e).__name__)
            return None

    async def available(self) -> bool:
        try:
            r = await self._client.get(f"{self.url}/health", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()


class HaikuProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self._client = httpx.AsyncClient(timeout=30.0)

    async def generate(self, prompt: str, max_tokens: int = 256,
                       temperature: float = 0.3) -> str | None:
        max_tokens = min(max_tokens, settings.MAX_LLM_TOKENS)
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        try:
            r = await self._client.post(
                "https://api.anthropic.com/v1/messages",
                json=payload, headers=headers,
            )
            r.raise_for_status()
            data = r.json()
            blocks = data.get("content", [])
            if not blocks:
                log.warning("Haiku returned empty content")
                return None
            return blocks[0].get("text")
        except Exception as e:
            log.warning("Haiku generate failed: %s", type(e).__name__)
            return None

    async def available(self) -> bool:
        return bool(self.api_key)

    async def aclose(self) -> None:
        await self._client.aclose()


class DeepSeekProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, base_url: str):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=30.0)

    async def generate(self, prompt: str, max_tokens: int = 256,
                       temperature: float = 0.3) -> str | None:
        max_tokens = min(max_tokens, settings.MAX_LLM_TOKENS)
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            r = await self._client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload, headers=headers,
            )
            r.raise_for_status()
            data = r.json()
            choices = data.get("choices", [])
            if not choices:
                log.warning("DeepSeek returned empty choices")
                return None
            return choices[0].get("message", {}).get("content")
        except Exception as e:
            log.warning("DeepSeek generate failed: %s", type(e).__name__)
            return None

    async def available(self) -> bool:
        return bool(self.api_key)

    async def aclose(self) -> None:
        await self._client.aclose()


_provider: LLMProvider | None = None

def init_llm_provider() -> LLMProvider | None:
    global _provider
    name = settings.ECODB_LLM_PROVIDER
    if name == "local":
        _provider = LlamaCppProvider(settings.LLAMA_CPP_URL)
    elif name == "haiku":
        key = settings.ANTHROPIC_API_KEY
        if not key:
            log.warning("ECODB_LLM_PROVIDER=haiku but ANTHROPIC_API_KEY not set")
            return None
        _provider = HaikuProvider(key, settings.HAIKU_MODEL)
    elif name == "deepseek":
        key = settings.DEEPSEEK_API_KEY
        if not key:
            log.warning("ECODB_LLM_PROVIDER=deepseek but DEEPSEEK_API_KEY not set")
            return None
        _provider = DeepSeekProvider(key, settings.DEEPSEEK_MODEL, settings.DEEPSEEK_URL)
    elif name == "off":
        _provider = None
    else:
        log.warning("Unknown ECODB_LLM_PROVIDER=%r, LLM disabled", name)
        _provider = None
    if _provider:
        log.info("LLM provider initialized: %s", name)
    return _provider

def get_llm_provider() -> LLMProvider | None:
    return _provider
