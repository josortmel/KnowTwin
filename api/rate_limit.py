"""Rate limiting middleware — per-user sliding window."""
from __future__ import annotations

import os
import time
from collections import defaultdict

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

import settings
from settings import RATE_LIMIT_SEARCH as SEARCH_LIMIT, RATE_LIMIT_DEFAULT as DEFAULT_LIMIT, RATE_LIMIT_WINDOW as WINDOW

RATE_LIMITS: dict[tuple[str, str], int] = {
    ("POST", "/memories/preview"): int(os.getenv("RATE_LIMIT_PREVIEW", "10")),
    ("POST", "/memories"): int(os.getenv("RATE_LIMIT_CREATE_MEMORY", "20")),
}


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self.requests: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        actor_id = "anon"
        auth = request.headers.get("authorization", "")
        token = auth.split(" ", 1)[1].strip() if " " in auth else ""

        if token.startswith(settings.API_KEY_PREFIX):
            from auth import hash_api_key
            actor_id = f"key:{hash_api_key(token)[:16]}"
        elif token and auth.lower().startswith("bearer "):
            try:
                import jwt
                payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
                actor_id = str(payload.get("sub", "anon"))
            except Exception:
                pass

        now = time.time()
        key = f"{actor_id}:{request.method}:{request.url.path}"

        self.requests[key] = [t for t in self.requests[key] if now - t < WINDOW]
        if not self.requests[key]:
            del self.requests[key]

        method_path = (request.method, request.url.path)
        if method_path in RATE_LIMITS:
            limit = RATE_LIMITS[method_path]
        elif "/search" in request.url.path:
            limit = SEARCH_LIMIT
        else:
            limit = DEFAULT_LIMIT

        if len(self.requests[key]) >= limit:
            retry_after = int(self.requests[key][0] + WINDOW - now) + 1
            retry_after = max(retry_after, 1)
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded"},
                headers={"Retry-After": str(retry_after)},
            )

        self.requests[key].append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(limit - len(self.requests[key]), 0))
        return response
