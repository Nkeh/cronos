from __future__ import annotations

import pytest_asyncio
from httpx import AsyncClient


@pytest_asyncio.fixture
async def csrf_headers(client: AsyncClient) -> dict[str, str]:
    """Fetches the CSRF cookie via GET /csrf and returns the matching header
    every mutating auth test needs — CSRFMiddleware requires both."""
    response = await client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    token = client.cookies.get("cronos_csrf")
    assert token
    return {"X-CSRF-Token": token}
