from __future__ import annotations

import uuid

from pydantic import BaseModel


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
