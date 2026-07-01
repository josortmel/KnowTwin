"""EcoDBRetriever — a LangChain ``BaseRetriever`` backed by EcoDB GAMR search.

Drop-in for any LangChain RAG chain: it turns a query into ``Document`` objects
whose ``page_content`` is the memory/document text and whose ``metadata`` carries
the EcoDB scores and ids, so downstream code can cite or re-rank.
"""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from .client import EcoDBClient


class EcoDBRetriever(BaseRetriever):
    """Retrieve EcoDB memories/documents as LangChain ``Document`` objects.

    Example::

        retriever = EcoDBRetriever(client=EcoDBClient(), k=6)
        docs = retriever.invoke("what did we decide about Azure?")
    """

    client: EcoDBClient
    k: int = 6
    query_type: Optional[str] = None
    type: Optional[str] = None
    include_documents: bool = True
    graph_discovery: bool = False

    model_config = {"arbitrary_types_allowed": True}

    def _get_relevant_documents(
        self, query: str, *, run_manager: Optional[CallbackManagerForRetrieverRun] = None
    ) -> list[Document]:
        data = self.client.search(
            query,
            limit=self.k,
            query_type=self.query_type,
            type=self.type,
            include_documents=self.include_documents,
            graph_discovery=self.graph_discovery,
        )
        docs: list[Document] = []
        for r in data.get("results", []):
            metadata: dict[str, Any] = {
                "id": r.get("id"),
                "type": r.get("type"),
                "source_type": r.get("source_type", "memory"),
                "score": r.get("score"),
                "semantic_score": r.get("semantic_score"),
                "graph_score": r.get("graph_score"),
                "freshness_score": r.get("freshness_score"),
                "tags": r.get("tags", []),
                "created_at": r.get("created_at"),
            }
            docs.append(Document(page_content=r.get("content") or "", metadata=metadata))
        return docs
