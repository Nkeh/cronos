from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.core.db import create_engine
from app.core.errors import register_error_handlers
from app.core.logging import RequestIDMiddleware, configure_logging
from app.core.redis import FailOpenRedis

logger = structlog.get_logger()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    settings.check_production_guard()

    engine = create_engine(settings)
    redis = FailOpenRedis(settings.redis_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = engine
        app.state.redis = redis
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
    register_error_handlers(app)

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
