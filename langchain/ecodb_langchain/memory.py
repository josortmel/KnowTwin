"""EcoDBMemory — durable, cross-session conversation memory backed by EcoDB.

Implements the classic LangChain memory interface (memory_variables /
load_memory_variables / save_context / clear) as a STANDALONE class, not a
subclass of langchain_core.memory.BaseMemory (removed in langchain-core 1.0).
Duck-type compatible, imports on every version. For graph-native agents, prefer
a LangGraph checkpointer; this exists for chains and for using EcoDB as the
durable store behind the familiar memory API.
"""

from __future__ import annotations

from typing import Any, Optional

from .client import EcoDBClient


class EcoDBMemory:
    """EcoDB-backed conversation memory (durable, cross-session)."""

    def __init__(
        self,
        client: EcoDBClient,
        *,
        memory_key: str = "history",
        k: int = 5,
        save_type: str = "momento",
        save_tags: Optional[list[str]] = None,
        input_key: Optional[str] = None,
        output_key: Optional[str] = None,
    ) -> None:
        self.client = client
        self.memory_key = memory_key
        self.k = k
        self.save_type = save_type
        self.save_tags = save_tags if save_tags is not None else ["conversation"]
        self.input_key = input_key
        self.output_key = output_key

    @property
    def memory_variables(self) -> list[str]:
        return [self.memory_key]

    def _first_value(self, d: dict[str, Any], preferred: Optional[str]) -> str:
        if preferred and preferred in d:
            return str(d[preferred])
        for v in d.values():
            if isinstance(v, str):
                return v
        return str(next(iter(d.values()), "")) if d else ""

    def load_memory_variables(self, inputs: dict[str, Any]) -> dict[str, Any]:
        query = self._first_value(inputs, self.input_key)
        if not query.strip():
            return {self.memory_key: ""}
        try:
            data = self.client.search(query, limit=self.k)
        except Exception:
            return {self.memory_key: ""}
        lines = [f"- ({r.get('type')}) {(r.get('content') or '')[:300]}" for r in data.get("results", [])]
        return {self.memory_key: "\n".join(lines)}

    def save_context(self, inputs: dict[str, Any], outputs: dict[str, Any]) -> None:
        human = self._first_value(inputs, self.input_key)
        ai = self._first_value(outputs, self.output_key)
        if not (human or ai):
            return
        content = f"Human: {human}\nAI: {ai}".strip()
        try:
            self.client.save_memory(content, type=self.save_type, tags=list(self.save_tags))
        except Exception:
            pass

    def clear(self) -> None:
        return None
