"""Unit tests for HttpProbe's exception -> error_kind mapping. Exercises the classifier via
HttpProbe.check against a transport double that raises the exception under test, so the
mapping is proven against the real except-chain in http_probe.py, not reimplemented here."""

from __future__ import annotations

import ssl
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpcore
import httpx
import pytest

from app.engine.claim import ClaimedMonitor
from app.engine.guarded_backend import BlockedAddressError, DnsResolutionError
from app.engine.http_probe import HttpProbe, _is_tls_failure


def _monitor(**overrides) -> ClaimedMonitor:
    defaults = dict(
        id=uuid.uuid4(),
        url="https://example.com/",
        method="GET",
        expected_status="2xx",
        timeout_seconds=5,
        scheduled_for=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return ClaimedMonitor(**defaults)


def _probe() -> HttpProbe:
    return HttpProbe(user_agent="Cronos/1.0 (+http://localhost/bot)")


async def _check_with_send_raising(exc: Exception):
    probe = _probe()
    with patch("httpx.AsyncClient.send", new=AsyncMock(side_effect=exc)):
        return await probe.check(_monitor())


async def test_blocked_address_error_maps_to_blocked() -> None:
    result = await _check_with_send_raising(BlockedAddressError("evil.example", "blocked"))
    assert result.is_up is False
    assert result.error_kind == "blocked"


async def test_dns_resolution_error_maps_to_dns() -> None:
    result = await _check_with_send_raising(DnsResolutionError("dns failed"))
    assert result.error_kind == "dns"


async def test_too_many_redirects_maps_to_redirects() -> None:
    result = await _check_with_send_raising(httpx.TooManyRedirects("too many redirects"))
    assert result.error_kind == "redirects"


async def test_stdlib_timeout_error_maps_to_timeout() -> None:
    result = await _check_with_send_raising(TimeoutError("timed out"))
    assert result.error_kind == "timeout"


async def test_httpx_connect_timeout_maps_to_timeout() -> None:
    result = await _check_with_send_raising(httpx.ConnectTimeout("connect timed out"))
    assert result.error_kind == "timeout"


async def test_connect_error_with_ssl_cause_maps_to_tls() -> None:
    cause = ssl.SSLError("certificate verify failed")
    exc = httpx.ConnectError("connect failed")
    exc.__cause__ = cause
    result = await _check_with_send_raising(exc)
    assert result.error_kind == "tls"


async def test_connect_error_without_ssl_cause_maps_to_connection() -> None:
    exc = httpx.ConnectError("connection refused")
    exc.__cause__ = OSError("refused")
    result = await _check_with_send_raising(exc)
    assert result.error_kind == "connection"


async def test_protocol_error_maps_to_connection() -> None:
    result = await _check_with_send_raising(httpx.RemoteProtocolError("bad response"))
    assert result.error_kind == "connection"


async def test_unclassified_exception_maps_to_connection() -> None:
    result = await _check_with_send_raising(RuntimeError("something weird"))
    assert result.error_kind == "connection"


async def test_status_mismatch_maps_to_http_status(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeResponse:
        status_code = 500

        async def aiter_bytes(self):
            return
            yield b""  # pragma: no cover - empty async generator

        async def aclose(self):
            return None

    probe = _probe()
    with patch("httpx.AsyncClient.send", new=AsyncMock(return_value=_FakeResponse())):
        result = await probe.check(_monitor(expected_status="2xx"))
    assert result.is_up is False
    assert result.error_kind == "http_status"
    assert result.status_code == 500


async def test_is_tls_failure_walks_explicit_cause_chain() -> None:
    original = ssl.SSLError("bad cert")
    middle = httpcore.ConnectError("wrapped")
    middle.__cause__ = original
    outer = httpx.ConnectError("wrapped again")
    outer.__cause__ = middle
    assert _is_tls_failure(outer) is True
    assert _is_tls_failure(httpx.ConnectError("plain")) is False


async def test_is_tls_failure_falls_back_to_context_when_cause_is_suppressed() -> None:
    """Verified empirically against the chaos tls-bad listener: httpcore's Trace
    instrumentation re-raises with `from None` at one hop, clearing __cause__, but __context__
    still carries the original ssl.SSLError since Python records it independent of `from`."""
    original = ssl.SSLError("bad cert")
    try:
        try:
            raise original
        except ssl.SSLError:
            raise httpcore.ConnectError("wrapped") from None
    except httpcore.ConnectError as middle:
        assert middle.__cause__ is None
        assert middle.__context__ is original
        assert _is_tls_failure(middle) is True
