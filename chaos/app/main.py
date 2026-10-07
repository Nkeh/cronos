"""A tiny misbehaving-website service.

Day 1 modes: up (200), down (a configurable 4xx/5xx), slow (delay N ms). The
rest of SRS §15's modes (flap, hang, redirect, big, tls-bad) land on Day 7
alongside the real probe and its SSRF test suite.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import FastAPI, Response
from pydantic import BaseModel

app = FastAPI(title="Cronos chaos target")

Mode = Literal["up", "down", "slow"]


class ControlEntry(BaseModel):
    mode: Mode = "up"
    status_code: int = 200
    delay_ms: int = 0


class SetControlRequest(BaseModel):
    path: str
    mode: Mode
    status_code: int = 200
    delay_ms: int = 0


_state: dict[str, ControlEntry] = {}


def _normalize(path: str) -> str:
    path = path if path.startswith("/") else f"/{path}"
    return path.rstrip("/") or "/"


@app.get("/_control")
async def get_control() -> dict[str, ControlEntry]:
    return _state


@app.post("/_control")
async def set_control(body: SetControlRequest) -> ControlEntry:
    entry = ControlEntry(mode=body.mode, status_code=body.status_code, delay_ms=body.delay_ms)
    _state[_normalize(body.path)] = entry
    return entry


@app.api_route("/{path:path}", methods=["GET", "HEAD"])
async def serve_target(path: str) -> Response:
    entry = _state.get(_normalize(path), ControlEntry())

    if entry.delay_ms:
        await asyncio.sleep(entry.delay_ms / 1000)

    if entry.mode == "down":
        return Response(status_code=entry.status_code)

    return Response(status_code=200, content=b"ok")
