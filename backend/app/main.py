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
from app.incidents.router import router as incidents_router
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
    app.include_router(incidents_router)
    if settings.env == "development":
        # Dev-only fixture endpoints for Playwright (no Docker access from the
        # pw-tests container) — never imported, let alone mounted, outside
        # real local development (not "test", not "production").
        from app.dev.router import router as dev_router

        app.include_router(dev_router)
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

        async with app.state.engine.connect() as conn:
            runner_row = (
                await conn.execute(
                    text(
                        "SELECT "
                        "EXISTS (SELECT 1 FROM runner_state "
                        "        WHERE last_tick_at > now() - interval '30 seconds') AS fresh, "
                        "NOT EXISTS (SELECT 1 FROM runner_state "
                        "            WHERE last_tick_at > now() - interval '30 seconds' "
                        "            AND NOT canary_ok) AS canary_ok"
                    )
                )
            ).one()
        checks["runner"] = "ok" if runner_row.fresh else "stale"
        # Canary health is reported but never fails readiness: a degraded canary means the
        # internet is unhealthy, not this process -- taking an otherwise-fine runner out of
        # rotation over that would help no one. Day 14's external watchdog is what acts on it.
        checks["canary"] = "ok" if runner_row.canary_ok else "degraded"
        if not runner_row.fresh:
            return JSONResponse(status_code=503, content={"status": "degraded", "checks": checks})

        # TODO (Day 9): also fail readiness if the outbox's oldest pending row is over 5 minutes old.

        return JSONResponse(status_code=200, content={"status": "ok", "checks": checks})

    return app


app = create_app()
