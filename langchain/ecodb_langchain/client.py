"""EcoDBClient — synchronous REST client for the EcoDB API.

Mirrors the request/auth behaviour of ``mcp/server.py`` (the proven MCP proxy):
exchange an API key for a JWT at ``/auth/token``, send it as a Bearer token,
and retry once on a 401 after refreshing. Endpoint paths and payload shapes are
copied 1:1 from the MCP tools so this client hits exactly what the MCP hits.

No business logic lives here — EcoDB's API is the source of truth. This is a
thin, faithful transport that the LangChain tools / retriever / memory / agent
build on top of.
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional
from urllib.parse import quote

import httpx

DEFAULT_BASE_URL = os.environ.get("ECODB_API_URL", "http://localhost:8080").rstrip("/")
DEFAULT_TIMEOUT = float(os.environ.get("ECODB_TIMEOUT", "30"))


class EcoDBError(RuntimeError):
    """Raised for API (>=400) or network errors. ``http_status`` is set for HTTP errors."""

    def __init__(self, message: str, http_status: Optional[int] = None):
        super().__init__(message)
        self.http_status = http_status


class EcoDBClient:
    """Synchronous client for the EcoDB REST API.

    Args:
        base_url: EcoDB API base URL. Defaults to ``$ECODB_API_URL`` or
            ``http://localhost:8080``.
        api_key: ``ecodb_...`` API key. Defaults to ``$ECODB_API_KEY``.
        agent_identifier: optional default agent identity used for saves/searches.
        default_workspace_id / default_project_id: defaults for writes (1/1).
        timeout: per-request timeout in seconds.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        *,
        agent_identifier: Optional[str] = None,
        default_workspace_id: int = 1,
        default_project_id: int = 1,
        timeout: Optional[float] = None,
    ) -> None:
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("ECODB_API_KEY", "")
        self.agent_identifier = agent_identifier
        self.default_workspace_id = default_workspace_id
        self.default_project_id = default_project_id
        self.timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        self._jwt: Optional[str] = None
        self._jwt_expires_at: float = 0.0

    # ------------------------------------------------------------------ auth
    def _ensure_jwt(self, client: httpx.Client, force_refresh: bool = False) -> str:
        now = time.time()
        if not force_refresh and self._jwt and now < self._jwt_expires_at - 60:
            return self._jwt
        if not self.api_key:
            raise EcoDBError("ECODB_API_KEY not configured (pass api_key= or set the env var)")
        r = client.post(f"{self.base_url}/auth/token", json={"api_key": self.api_key})
        if r.status_code != 200:
            raise EcoDBError(f"auth/token failed: HTTP {r.status_code}", r.status_code)
        try:
            data = r.json()
        except Exception:
            raise EcoDBError(f"auth/token returned non-JSON: {r.text[:200]}")
        try:
            self._jwt = data["access_token"]
        except KeyError:
            raise EcoDBError(f"auth/token response missing 'access_token': keys={list(data.keys())}")
        self._jwt_expires_at = now + float(data.get("expires_in", 3600))
        return self._jwt

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        """HTTP call with automatic auth + single-shot retry after 401.

        Mirrors ``_api_call`` in mcp/server.py.
        """
        try:
            with httpx.Client(timeout=self.timeout) as client:
                token = self._ensure_jwt(client)
                headers = kwargs.pop("headers", {}) or {}
                headers["Authorization"] = f"Bearer {token}"
                url = f"{self.base_url}{path}"
                r = client.request(method, url, headers=headers, **kwargs)
                if r.status_code == 401:
                    token = self._ensure_jwt(client, force_refresh=True)
                    headers["Authorization"] = f"Bearer {token}"
                    r = client.request(method, url, headers=headers, **kwargs)
                if r.status_code >= 400:
                    try:
                        detail = r.json()
                        import json as _json
                        detail_str = _json.dumps(detail, ensure_ascii=False)
                    except Exception:
                        detail_str = r.text[:300]
                    raise EcoDBError(f"{method} {path} -> HTTP {r.status_code}: {detail_str}", r.status_code)
                if r.status_code == 204:
                    return {"ok": True}
                return r.json()
        except httpx.HTTPError as e:
            raise EcoDBError(f"{method} {path}: network error ({type(e).__name__}): {e}")

    # --------------------------------------------------------------- memories
    def search(
        self,
        query_text: Optional[str] = None,
        *,
        query_image: Optional[str] = None,
        query_type: Optional[str] = None,
        modality_filter: str = "all",
        limit: int = 20,
        workspace_id: Optional[int] = None,
        project_id: Optional[int] = None,
        type: Optional[str] = None,
        agent_identifier: Optional[str] = None,
        fecha_desde: Optional[str] = None,
        fecha_hasta: Optional[str] = None,
        expand_scope: bool = False,
        graph_discovery: bool = False,
        include_documents: bool = True,
        max_document_results: int = 3,
        tags: Optional[list[str]] = None,
        deep_factor: int = 2,
    ) -> dict:
        """GAMR multi-stage search. POST /search. Returns the raw API dict (``results`` + metadata)."""
        if query_text is None and query_image is None:
            raise EcoDBError("at least one of query_text or query_image is required")
        if not 1 <= limit <= 100:
            raise EcoDBError("limit must be between 1 and 100")
        payload: dict = {"limit": limit, "expand_scope": expand_scope, "modality_filter": modality_filter}
        if query_text is not None:
            payload["query_text"] = query_text
        if query_image is not None:
            payload["query_image"] = query_image
        if query_type is not None:
            payload["query_type"] = query_type
        if workspace_id is not None:
            payload["workspace_id"] = workspace_id
        if project_id is not None:
            payload["project_id"] = project_id
        if type is not None:
            payload["type"] = type
        agent = agent_identifier if agent_identifier is not None else self.agent_identifier
        if agent is not None:
            payload["agent_identifier"] = agent
        if fecha_desde is not None:
            payload["fecha_desde"] = fecha_desde
        if fecha_hasta is not None:
            payload["fecha_hasta"] = fecha_hasta
        if graph_discovery:
            payload["graph_discovery"] = True
        if include_documents:
            payload["include_documents"] = True
            payload["max_document_results"] = max_document_results
        if tags:
            payload["tags"] = tags
        if deep_factor != 2:
            payload["deep_factor"] = deep_factor
        return self._call("POST", "/search", json=payload)

    def search_recent(
        self,
        *,
        limit: int = 20,
        workspace_id: Optional[int] = None,
        project_id: Optional[int] = None,
        agent_identifier: Optional[str] = None,
        fecha_desde: Optional[str] = None,
        fecha_hasta: Optional[str] = None,
        tags: Optional[list[str]] = None,
        expand_scope: bool = False,
    ) -> dict:
        """Recent memories filtered by actor permissions. GET /memories/recent."""
        params: dict = {"limit": limit, "expand_scope": expand_scope}
        if workspace_id is not None:
            params["workspace_id"] = workspace_id
        if project_id is not None:
            params["project_id"] = project_id
        agent = agent_identifier if agent_identifier is not None else self.agent_identifier
        if agent is not None:
            params["agent_identifier"] = agent
        if fecha_desde is not None:
            params["fecha_desde"] = fecha_desde
        if fecha_hasta is not None:
            params["fecha_hasta"] = fecha_hasta
        if tags is not None:
            params["tags"] = tags
        return self._call("GET", "/memories/recent", params=params)

    def save_memory(
        self,
        content: str,
        *,
        type: str = "observacion",
        workspace_id: Optional[int] = None,
        project_id: Optional[int] = None,
        tags: Optional[list[str]] = None,
        visibility: str = "public",
        agent_identifier: Optional[str] = None,
        image_base64: Optional[str] = None,
    ) -> dict:
        """Save a memory. POST /memories. Returns the created memory dict."""
        payload: dict = {
            "content": content,
            "type": type,
            "workspace_id": workspace_id if workspace_id is not None else self.default_workspace_id,
            "project_id": project_id if project_id is not None else self.default_project_id,
            "visibility": visibility,
            "tags": tags or [],
        }
        agent = agent_identifier if agent_identifier is not None else self.agent_identifier
        if agent is not None:
            payload["agent_identifier"] = agent
        if image_base64 is not None:
            payload["image_base64"] = image_base64
        return self._call("POST", "/memories", json=payload)

    def read_memory(self, memory_id: str, *, expand_scope: bool = False) -> dict:
        """Read a memory by id (increments access_count). GET /memories/{id}."""
        params = {"expand_scope": expand_scope} if expand_scope else None
        return self._call("GET", f"/memories/{quote(memory_id, safe='')}", params=params)

    # ------------------------------------------------------------------ graph
    def neighbors(self, node: str, *, depth: int = 1) -> dict:
        """Graph neighbours of a node, 1-3 hops. GET /graph/neighbors/{node}."""
        depth = max(1, min(int(depth), 3))
        return self._call("GET", f"/graph/neighbors/{quote(node, safe='')}", params={"depth": depth})

    def path_between(self, source: str, target: str, *, max_depth: int = 6) -> dict:
        """Shortest path between two graph nodes. GET /graph/path."""
        max_depth = max(1, min(int(max_depth), 10))
        return self._call("GET", "/graph/path", params={"source": source, "target": target, "max_depth": max_depth})

    def search_nodes(self, query: str, *, limit: int = 20) -> dict:
        """Fuzzy node search by name (pg_trgm). GET /graph/search.
        API returns {"query": ..., "matches": [...]}."""
        if len(query.strip()) < 3:
            raise EcoDBError("query must be at least 3 characters")
        limit = max(1, min(int(limit), 100))
        return self._call("GET", "/graph/search", params={"q": query, "limit": limit})

    def graph_status(self) -> dict:
        """Graph statistics. GET /graph/stats."""
        return self._call("GET", "/graph/stats")

    def save_triple(self, subject: str, predicate: str, object: str, *, author: Optional[str] = None) -> dict:
        """Save a subject-predicate-object triple. POST /graph/triples."""
        payload: dict = {"subject": subject, "predicate": predicate, "object": object}
        if author is not None:
            payload["author"] = author
        return self._call("POST", "/graph/triples", json=payload)

    # --------------------------------------------------------------- identity
    def load_identity(self, agent_identifier: str, *, version: Optional[int] = None) -> dict:
        """Load an agent's identity fragments. GET /agents/{id}/identity."""
        params = {"version": version} if version is not None else None
        return self._call("GET", f"/agents/{quote(agent_identifier, safe='')}/identity", params=params)

    # --------------------------------------------------------------- clusters (Memory Agent v1.3)
    def search_clusters(self, query_text: str, *, agent_identifier: Optional[str] = None,
                        level: Optional[str] = None, status: str = "active", limit: int = 10) -> dict:
        """Semantic search over memory clusters (centroid cosine + label BM25).
        POST /api/v1/clusters/search. Without agent_identifier, returns only SIN_AUTOR
        (generic/technical) clusters for non-super actors."""
        payload: dict = {"query_text": query_text, "status": status, "limit": limit}
        agent = agent_identifier if agent_identifier is not None else self.agent_identifier
        if agent is not None:
            payload["agent_identifier"] = agent
        if level is not None:
            payload["level"] = level
        return self._call("POST", "/api/v1/clusters/search", json=payload)

    def list_clusters(self, agent_identifier: str, *, level: Optional[str] = None,
                     status: str = "active", limit: int = 20) -> dict:
        """List clusters by agent, level, status. GET /api/v1/clusters."""
        params: dict = {"agent_identifier": agent_identifier, "status": status, "limit": limit}
        if level is not None:
            params["level"] = level
        return self._call("GET", "/api/v1/clusters", params=params)

    def read_cluster(self, cluster_id: str, *, include_members: bool = False,
                    include_sources: bool = False) -> dict:
        """Read a cluster with optional members + telescopic sources. GET /api/v1/clusters/{id}."""
        data = self._call("GET", f"/api/v1/clusters/{quote(cluster_id, safe='')}")
        if include_members:
            data["members"] = self._call("GET", f"/api/v1/clusters/{quote(cluster_id, safe='')}/members")
        if include_sources:
            data["sources"] = self._call("GET", f"/api/v1/clusters/{quote(cluster_id, safe='')}/sources")
        return data

    def get_telescopic_view(self, agent_identifier: str,
                           levels: str = "weekly,monthly,quarterly,yearly") -> dict:
        """Load an agent's fractal memory chain for boot. GET /api/v1/clusters/telescopic."""
        return self._call("GET", "/api/v1/clusters/telescopic",
                         params={"agent_identifier": agent_identifier, "levels": levels})

    def get_briefing(self, agent_identifier: str) -> dict:
        """Agent briefing: foresights + tensions + telescopic summary. GET /api/v1/briefing."""
        return self._call("GET", "/api/v1/briefing", params={"agent_identifier": agent_identifier})
