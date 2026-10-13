"""Thin FastAPI dependencies reading objects off app.state.

Everything here is set once in main.py's lifespan; these just give route code
a `Depends(...)` seam instead of reaching into `request.app.state` directly.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from fastapi import Request

from app.core.clock import Clock
from app.core.config import Settings
from app.core.email import EmailSender
from app.core.redis import FailOpenRedis


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def get_redis(request: Request) -> FailOpenRedis:
    return request.app.state.redis


def get_password_hasher(request: Request) -> PasswordHasher:
    return request.app.state.password_hasher


def get_dummy_password_hash(request: Request) -> str:
    return request.app.state.dummy_password_hash


def get_email_sender(request: Request) -> EmailSender:
    return request.app.state.email_sender
