"""API key management: GET/POST /api/v1/api-keys, DELETE /api/v1/api-keys/{id}.

Session-only (CLAUDE.md Day 4 rule): an API key presenting itself here gets
403 session_required (require_verified_session_user), never a silent
downgrade to treating it like a session.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_keys import ALL_SCOPES, generate_api_key
from app.auth.dependencies import require_verified_session_user
from app.auth.models import ApiKey, User
from app.auth.schemas import ApiKeyCreateRequest, ApiKeyCreateResponse, ApiKeyPublic
from app.core.db import get_db_session
from app.core.errors import ApiError
from app.plans.dependencies import check_limit, get_account_for_update

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/api-keys", tags=["api-keys"])

_MAX_PREFIX_COLLISION_RETRIES = 3


def _to_public(row: ApiKey) -> ApiKeyPublic:
    return ApiKeyPublic(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        scopes=row.scopes,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
    )


@router.get("", response_model=list[ApiKeyPublic])
async def list_api_keys(
    user: User = Depends(require_verified_session_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[ApiKeyPublic]:
    rows = (
        (
            await db.execute(
                select(ApiKey)
                .where(ApiKey.account_id == user.account_id)
                .order_by(ApiKey.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_to_public(row) for row in rows]


@router.post("", response_model=ApiKeyCreateResponse, status_code=201)
async def create_api_key(
    payload: ApiKeyCreateRequest,
    user: User = Depends(require_verified_session_user),
    db: AsyncSession = Depends(get_db_session),
) -> ApiKeyCreateResponse:
    if not payload.scopes:
        raise ApiError(422, "validation_error", "At least one scope is required.", field="scopes")
    invalid_scopes = sorted(set(payload.scopes) - ALL_SCOPES)
    if invalid_scopes:
        raise ApiError(
            422, "validation_error", f"Unknown scopes: {invalid_scopes}.", field="scopes"
        )

    account = await get_account_for_update(db, user.account_id)
    await check_limit(db, account, "api_keys")

    full_key: str | None = None
    row: ApiKey | None = None
    for attempt in range(_MAX_PREFIX_COLLISION_RETRIES):
        full_key, prefix, key_hash = generate_api_key()
        candidate = ApiKey(
            account_id=account.id,
            name=payload.name,
            prefix=prefix,
            key_hash=key_hash,
            scopes=payload.scopes,
            created_by_user_id=user.id,
        )
        try:
            async with db.begin_nested():
                db.add(candidate)
                await db.flush()
            row = candidate
            break
        except IntegrityError:
            logger.warning("api_key_prefix_collision", attempt=attempt)
            continue
    else:
        raise ApiError(500, "internal_error", "Could not generate a unique API key.")

    assert row is not None and full_key is not None
    await db.commit()
    logger.info("api_key_created", api_key_id=str(row.id), account_id=str(account.id))
    return ApiKeyCreateResponse(**_to_public(row).model_dump(), key=full_key)


@router.delete("/{api_key_id}", status_code=204)
async def revoke_api_key(
    api_key_id: uuid.UUID,
    user: User = Depends(require_verified_session_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    row = (
        await db.execute(
            select(ApiKey).where(ApiKey.id == api_key_id, ApiKey.account_id == user.account_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "API key not found.")

    if row.revoked_at is None:
        await db.execute(
            update(ApiKey).where(ApiKey.id == row.id).values(revoked_at=text("now()"))
        )
        await db.commit()
    logger.info("api_key_revoked", api_key_id=str(row.id), account_id=str(user.account_id))
