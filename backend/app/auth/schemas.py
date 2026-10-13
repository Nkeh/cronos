from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SignupRequest(BaseModel):
    email: str
    password: str


class SignupResponse(BaseModel):
    message: str


class VerifyRequest(BaseModel):
    token: str


class VerifyResponse(BaseModel):
    message: str


class VerifyResendRequest(BaseModel):
    pass


class VerifyResendResponse(BaseModel):
    message: str


class LoginRequest(BaseModel):
    email: str
    password: str


class LogoutRequest(BaseModel):
    pass


class UserPublic(BaseModel):
    user_id: uuid.UUID
    email: str
    email_verified: bool
    account_id: uuid.UUID
    plan: str


class ResetRequestRequest(BaseModel):
    email: str


class ResetRequestResponse(BaseModel):
    message: str


class ResetRequest(BaseModel):
    token: str
    password: str


class ResetResponse(BaseModel):
    message: str


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    scopes: list[str]


class ApiKeyPublic(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreateResponse(ApiKeyPublic):
    key: str
