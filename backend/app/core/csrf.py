"""CSRF double-submit + same-origin enforcement, as blanket middleware.

A blanket middleware (not a per-route Depends) is deliberate: the rule is
"every state-changing /api request, cookie-authenticated or pre-auth" — a new
route gets this protection automatically, with nothing to remember to attach.
"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.auth.constants import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.core.config import Settings

_STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_CONTENT_TYPE_CHECKED_METHODS = frozenset({"POST", "PUT", "PATCH"})


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})


class CSRFMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in _STATE_CHANGING_METHODS:
            return await call_next(request)
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        if request.headers.get("Authorization"):
            # Day 4 placeholder: API-key-authenticated requests are exempt.
            return await call_next(request)

        origin = request.headers.get("Origin")
        if origin is not None and origin != self._settings.public_origin:
            return _error(403, "origin_rejected", "Origin not allowed.")

        if request.method in _CONTENT_TYPE_CHECKED_METHODS:
            content_type = request.headers.get("Content-Type", "").split(";")[0].strip()
            if content_type != "application/json":
                return _error(415, "unsupported_media_type", "Content-Type must be application/json.")

        cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
        header_token = request.headers.get(CSRF_HEADER_NAME)
        if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
            return _error(403, "csrf_failed", "CSRF token missing or invalid.")

        return await call_next(request)
