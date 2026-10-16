"""A tiny misbehaving-website service.

Day 1 modes: up (200), down (a configurable 4xx/5xx), slow (delay N ms). Day 7 adds the rest of
SRS Section 15's modes (flap, hang, redirect, big, tls-bad), a /whoami endpoint for proving
fresh-connection behavior, and a minimal webhook-receiver stub.
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from typing import AsyncIterator, Literal

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel

from app.tls_bad_cert import ensure_tls_bad_cert

Mode = Literal["up", "down", "slow", "flap", "hang", "redirect", "big", "tls_bad"]

_HANG_BACKSTOP_SECONDS = 300
_HANG_POLL_SECONDS = 0.5
_BIG_CHUNK_SIZE = 65536


class ControlEntry(BaseModel):
    mode: Mode = "up"
    status_code: int = 200
    delay_ms: int = 0
    flap_every: int = 1
    redirect_url: str | None = None
    redirect_status: int = 302
    big_bytes: int = 50 * 1024 * 1024


class SetControlRequest(BaseModel):
    path: str
    mode: Mode
    status_code: int = 200
    delay_ms: int = 0
    flap_every: int = 1
    redirect_url: str | None = None
    redirect_status: int = 302
    big_bytes: int = 50 * 1024 * 1024


_state: dict[str, ControlEntry] = {}
_request_counts: dict[str, int] = {}
_webhook_log: list[dict] = []


def _normalize(path: str) -> str:
    path = path if path.startswith("/") else f"/{path}"
    return path.rstrip("/") or "/"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Second listener, same app, on the TLS-bad port -- the bad-cert failure happens at the
    # handshake, before any route logic runs, so there's no reason to maintain a second app.
    cert_path, key_path = ensure_tls_bad_cert()
    tls_server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0",
            port=8443,
            ssl_certfile=cert_path,
            ssl_keyfile=key_path,
            log_level="warning",
            # "off": this Server serves the SAME app object the outer (CMD-launched) uvicorn
            # process is already running startup/shutdown for -- without this, the ASGI
            # lifespan protocol would fire a second time here, re-entering this very
            # lifespan() context manager and trying to start a third listener on an
            # already-bound port 8443.
            lifespan="off",
        )
    )
    # uvicorn.Server.serve() unconditionally grabs SIGINT/SIGTERM for the duration of the call
    # (Server.capture_signals, gated only on "is this the main thread" -- true here, since this
    # runs as an asyncio task on the SAME thread/loop as the outer CMD-launched uvicorn server).
    # Two Servers both doing that in one process means the second to start wins the signal
    # handler, and the first (outer, real) server would then never see should_exit on a real
    # SIGTERM. The TLS-bad listener's own signal handling is irrelevant to this service's
    # lifecycle, so neutralize it at the instance level instead.
    tls_server.capture_signals = lambda: contextlib.nullcontext()
    tls_task = asyncio.create_task(tls_server.serve())
    try:
        yield
    finally:
        tls_server.should_exit = True
        await tls_task


app = FastAPI(title="Cronos chaos target", lifespan=lifespan)


@app.get("/_control")
async def get_control() -> dict[str, ControlEntry]:
    return _state


@app.post("/_control")
async def set_control(body: SetControlRequest) -> ControlEntry:
    entry = ControlEntry(
        mode=body.mode,
        status_code=body.status_code,
        delay_ms=body.delay_ms,
        flap_every=body.flap_every,
        redirect_url=body.redirect_url,
        redirect_status=body.redirect_status,
        big_bytes=body.big_bytes,
    )
    _state[_normalize(body.path)] = entry
    return entry


@app.get("/whoami")
async def whoami(request: Request) -> dict:
    """Lets tests prove a fresh connection per check: the client source port differs across
    consecutive probes against the same monitor."""
    client = request.client
    return {
        "user_agent": request.headers.get("user-agent"),
        "client_port": client.port if client else None,
    }


@app.post("/webhook")
async def receive_webhook(request: Request) -> Response:
    """Minimal stub: logs what arrived and returns a status code configurable through the same
    /_control machinery as everything else (POST /_control {"path": "/webhook", "mode": "down",
    "status_code": 500}).

    DAY 9 TODO: real HMAC-SHA256(secret, timestamp + "." + body) signature verification, once
    the notifier's signing code exists to test against. For now this only records what arrived.
    """
    body = await request.body()
    _webhook_log.append(
        {
            "signature_header": request.headers.get("X-Cronos-Signature"),
            "body_length": len(body),
            "verified": None,
        }
    )
    entry = _state.get("/webhook", ControlEntry())
    return Response(status_code=entry.status_code)


@app.get("/_webhook/_log")
async def get_webhook_log() -> list[dict]:
    return _webhook_log


async def _big_body_chunks(total_bytes: int) -> AsyncIterator[bytes]:
    chunk = b"x" * _BIG_CHUNK_SIZE
    sent = 0
    while sent < total_bytes:
        piece = chunk if total_bytes - sent >= len(chunk) else chunk[: total_bytes - sent]
        yield piece
        sent += len(piece)


@app.api_route("/{path:path}", methods=["GET", "HEAD"])
async def serve_target(path: str, request: Request) -> Response:
    key = _normalize(path)
    entry = _state.get(key, ControlEntry())

    if entry.delay_ms:
        await asyncio.sleep(entry.delay_ms / 1000)

    if entry.mode == "down":
        return Response(status_code=entry.status_code)

    if entry.mode == "flap":
        _request_counts[key] = _request_counts.get(key, 0) + 1
        cycle = (_request_counts[key] - 1) // max(entry.flap_every, 1)
        if cycle % 2 == 0:
            return Response(status_code=200, content=b"ok")
        return Response(status_code=entry.status_code)

    if entry.mode == "hang":
        # Accepts the connection and never responds, but bounded on this side so repeated hang
        # checks don't accumulate stuck server-side tasks: a 300s backstop (far longer than any
        # real timeout_seconds a monitor would use) plus polling for the client disconnecting
        # first, which is what actually happens once the probe's own deadline fires.
        elapsed = 0.0
        while elapsed < _HANG_BACKSTOP_SECONDS:
            if await request.is_disconnected():
                break
            await asyncio.sleep(_HANG_POLL_SECONDS)
            elapsed += _HANG_POLL_SECONDS
        return Response(status_code=200, content=b"ok")

    if entry.mode == "redirect":
        return RedirectResponse(url=entry.redirect_url or "/", status_code=entry.redirect_status)

    if entry.mode == "big":
        return StreamingResponse(_big_body_chunks(entry.big_bytes), status_code=200)

    # "up" and "tls_bad" (meaningful only via the TLS-bad listener on 8443) both serve normally
    # on the plain port.
    return Response(status_code=200, content=b"ok")
