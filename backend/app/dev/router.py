"""Dev-only HTTP fixtures, used by Playwright.

Mirrors app.cli exactly — same app.dev_fixtures functions underneath — but
reachable over HTTP, since the pw-tests container has no Docker access to
shell into the api container. Only mounted by create_app() when
settings.env == "development" (see app/main.py): there is no route here at
all in "test" or "production", not a guarded 404 inside the handler.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.dependencies import get_clock, get_password_hasher, get_settings_dep
from app.core.errors import ApiError
from app.dev_fixtures import SeedError
from app.dev_fixtures import create_user as create_user_row
from app.dev_fixtures import delete_account_by_email
from app.dev_fixtures import seed_monitors as seed_monitor_rows

router = APIRouter(prefix="/api/v1/_dev", tags=["dev"])


class DevCreateUserRequest(BaseModel):
    email: str
    password: str
    verified: bool = False


class DevCreateUserResponse(BaseModel):
    user_id: str
    account_id: str
    email: str


class DevSeedMonitorsRequest(BaseModel):
    email: str
    count: int = Field(default=6, ge=0, le=15)


class DevSeedMonitorsResponse(BaseModel):
    created: int


class DevDeleteUserRequest(BaseModel):
    email: str


@router.post("/users", response_model=DevCreateUserResponse, status_code=201)
async def dev_create_user(
    payload: DevCreateUserRequest,
    db: AsyncSession = Depends(get_db_session),
    hasher: PasswordHasher = Depends(get_password_hasher),
    clock: Clock = Depends(get_clock),
) -> DevCreateUserResponse:
    try:
        user = await create_user_row(
            db,
            email=payload.email,
            password=payload.password,
            verified=payload.verified,
            hasher=hasher,
            clock=clock,
        )
    except SeedError as exc:
        raise ApiError(409, "dev_fixture_conflict", str(exc)) from None
    await db.commit()
    return DevCreateUserResponse(
        user_id=str(user.id), account_id=str(user.account_id), email=user.email
    )


@router.post("/seed-monitors", response_model=DevSeedMonitorsResponse, status_code=201)
async def dev_seed_monitors(
    payload: DevSeedMonitorsRequest,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
) -> DevSeedMonitorsResponse:
    try:
        monitors = await seed_monitor_rows(
            db, email=payload.email, count=payload.count, settings=settings
        )
    except SeedError as exc:
        raise ApiError(409, "dev_fixture_conflict", str(exc)) from None
    await db.commit()
    return DevSeedMonitorsResponse(created=len(monitors))


@router.post("/users/delete", status_code=204)
async def dev_delete_user(
    payload: DevDeleteUserRequest,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Idempotent: deleting a nonexistent email is a no-op, not a 404 — this exists purely so
    Playwright's global-setup can reset fixture accounts against the persistent dev database."""
    await delete_account_by_email(db, payload.email)
    await db.commit()
