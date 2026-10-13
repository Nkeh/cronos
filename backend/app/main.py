from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.accounts.router import router as accounts_router
from app.auth.api_keys_router import router as api_keys_router
from app.auth.router import router as auth_router
from app.auth.security import build_dummy_hash, build_password_hasher
from app.core.clock import Clock, SystemClock
from app.core.config import Settings, get_settings
from app.core.csrf import CSRFMiddleware
from app.core.db import create_engine, create_session_factory
from app.core.email import EmailSender, SMTPEmailSender
from app.core.errors import register_error_handlers
from app.core.logging import RequestIDMiddleware, configure_logging
from app.core.openapi import custom_openapi
from app.core.redis import FailOpenRedis
from app.monitors.router import router as monitors_router

logger = structlog.get_logger()


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    email_sender: EmailSender | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    settings.check_production_guard()

    clock = clock or SystemClock()
    engine = create_engine(settings)
    redis = FailOpenRedis(settings.redis_url)
    password_hasher = build_password_hasher(settings)
    dummy_password_hash = build_dummy_hash(password_hasher)
    resolved_email_sender = email_sender or SMTPEmailSender(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.redis = redis
        app.state.clock = clock
        app.state.password_hasher = password_hasher
        app.state.dummy_password_hash = dummy_password_hash
        app.state.email_sender = resolved_email_sender
        logger.info("api_started", env=settings.env)
        yield
        await engine.dispose()
        await redis.close()
        logger.info("api_stopped")

    app = FastAPI(
        title="Cronos API",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(CSRFMiddleware, settings=settings)
    register_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(api_keys_router)
    app.include_router(accounts_router)
    app.include_router(monitors_router)
    app.openapi = lambda: custom_openapi(app)  # documents both cookie and bearer auth

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        checks = {"db": "ok", "redis": "ok"}

        try:
            async with app.state.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 - any DB failure means not ready
            logger.error("readyz_db_failed", error=str(exc))
            checks["db"] = "unavailable"
            return JSONResponse(status_code=503, content={"status": "degraded", "checks": checks})

        if not await app.state.redis.ping():
            # Redis is non-critical: report it, never fail readiness for it.
            checks["redis"] = "unavailable"

        # TODO (Day 6): also fail readiness if no runner has ticked within 30s (runner_state).
        # TODO (Day 9): also fail readiness if the outbox's oldest pending row is over 5 minutes old.

        return JSONResponse(status_code=200, content={"status": "ok", "checks": checks})

    return app


app = create_app()
