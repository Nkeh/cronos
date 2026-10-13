"""Documents both auth schemes (cookie session, bearer API key) in OpenAPI.

Documentation only — the real auth dependencies (current_principal etc.) are
Request-based, not fastapi.security.*, so this doesn't change any actual
auth behavior; it only makes /api/docs show both schemes.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.auth.constants import SESSION_COOKIE_NAME


def custom_openapi(app: FastAPI) -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(title=app.title, version="1.0.0", routes=app.routes)
    schema.setdefault("components", {})["securitySchemes"] = {
        "cookieAuth": {"type": "apiKey", "in": "cookie", "name": SESSION_COOKIE_NAME},
        "bearerAuth": {"type": "http", "scheme": "bearer"},
    }
    schema["security"] = [{"cookieAuth": []}, {"bearerAuth": []}]

    app.openapi_schema = schema
    return app.openapi_schema
