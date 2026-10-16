"""The real HTTP probe behind the Day 6 Probe protocol.

Fresh connection per check (no pooling, which would hide connection failures), SSRF-guarded at
connect time via app.engine.guarded_backend, bounded body read, phase timings, and a short
vocabulary of error_kind classifications so incidents/notifications (Day 8/9) and the UI can
tell "the target is slow" apart from "DNS is broken" apart from "we blocked this as SSRF"
without parsing free-text error messages.
"""

from __future__ import annotations

import asyncio
import ssl
import time
from urllib.parse import urlsplit

import certifi
import httpcore
import httpx
import structlog

from app.engine.claim import ClaimedMonitor
from app.engine.guarded_backend import (
    BlockedAddressError,
    ConnectTimings,
    DnsResolutionError,
    GuardedBackend,
)
from app.engine.probe import ProbeResult

logger = structlog.get_logger()

_MAX_ERROR_LENGTH = 500


def _redact_url(url: str) -> str:
    """Strips the query string and fragment before a URL ever reaches a log line -- a monitor
    URL can carry a user-controlled query string (e.g. an API token), and logs are not the
    place for that. check_results.error may keep a short message of its own; this helper is
    for log lines only."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _is_tls_failure(exc: BaseException) -> bool:
    """Walks the full cause/context chain looking for the original ssl.SSLError. httpcore and
    httpx both re-wrap network exceptions as they propagate, but verified empirically (against
    the chaos tls-bad listener) that httpcore's own Trace instrumentation re-raises with `from
    None` at one hop -- __cause__ goes missing there, but __context__ still carries the
    original ssl.SSLError (Python always records __context__ for an exception raised while
    another is active, independent of any explicit `from` clause). So this walks __cause__ when
    present, falling back to __context__, at every hop."""
    seen: BaseException | None = exc
    visited: set[int] = set()
    while seen is not None and id(seen) not in visited:
        visited.add(id(seen))
        if isinstance(seen, ssl.SSLError):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


class HttpProbe:
    """Explicit constructor args, not a hidden Settings read -- mirrors StubProbe's own
    pattern. runner.py builds the real instance from Settings."""

    def __init__(
        self,
        *,
        user_agent: str,
        max_redirects: int = 3,
        body_cap_bytes: int = 65536,
        allow_hosts: frozenset[str] = frozenset(),
    ) -> None:
        self._user_agent = user_agent
        self._max_redirects = max_redirects
        self._body_cap_bytes = body_cap_bytes
        self._allow_hosts = allow_hosts

    async def check(self, monitor: ClaimedMonitor) -> ProbeResult:
        timings = ConnectTimings()
        backend = GuardedBackend(timings=timings, allow_hosts=self._allow_hosts)

        # Built from the stdlib + certifi directly, not httpx._config.create_ssl_context --
        # that keeps us off a second private httpx function on top of the already-private
        # `_pool` attribute swapped in below.
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        transport = httpx.AsyncHTTPTransport(trust_env=False, retries=0)
        # Reaches into httpx's private _pool attribute to swap in our guarded backend -- the
        # one place a future httpx/httpcore upgrade could silently stop routing connections
        # through our SSRF guard. tests/engine/test_http_probe_seam.py's
        # test_blocked_address_through_real_transport is the canary: it drives a real
        # HttpProbe end-to-end against a blocked address and must fail loudly if this seam
        # breaks. Do not remove or weaken that test without replacing this comment's claim.
        transport._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_context,
            network_backend=backend,
            max_connections=1,
            max_keepalive_connections=0,
            retries=0,
        )

        t_start = time.monotonic()
        ttfb_ms: float | None = None
        try:
            async with httpx.AsyncClient(
                transport=transport,
                trust_env=False,
                timeout=httpx.Timeout(monitor.timeout_seconds),
                follow_redirects=True,
                max_redirects=self._max_redirects,
            ) as client:
                async with asyncio.timeout(monitor.timeout_seconds):
                    request = client.build_request(
                        monitor.method,
                        monitor.url,
                        headers={"User-Agent": self._user_agent, "Accept": "*/*"},
                    )
                    response = await client.send(request, stream=True)
                    ttfb_ms = (time.monotonic() - t_start) * 1000
                    read = 0
                    async for chunk in response.aiter_bytes():
                        read += len(chunk)
                        if read >= self._body_cap_bytes:
                            break
                    await response.aclose()
        except BlockedAddressError:
            return self._failure(monitor, timings, t_start, ttfb_ms, "blocked", "blocked")
        except DnsResolutionError:
            return self._failure(monitor, timings, t_start, ttfb_ms, "dns", "dns")
        except httpx.TooManyRedirects:
            return self._failure(monitor, timings, t_start, ttfb_ms, "too many redirects", "redirects")
        except (TimeoutError, httpx.TimeoutException):
            return self._failure(monitor, timings, t_start, ttfb_ms, "timed out", "timeout")
        except (
            httpx.ConnectError,
            httpx.NetworkError,
            httpx.ProtocolError,
            httpx.RemoteProtocolError,
            httpx.LocalProtocolError,
        ) as exc:
            kind = "tls" if _is_tls_failure(exc) else "connection"
            return self._failure(monitor, timings, t_start, ttfb_ms, str(exc), kind)
        except Exception as exc:  # noqa: BLE001 - one monitor's failure must never crash the runner
            logger.warning(
                "probe_unclassified_error",
                monitor_id=str(monitor.id),
                url=_redact_url(monitor.url),
                error=str(exc)[:_MAX_ERROR_LENGTH],
            )
            return self._failure(monitor, timings, t_start, ttfb_ms, str(exc), "connection")

        total_ms = (time.monotonic() - t_start) * 1000
        timings_out = self._collect_timings(timings, ttfb_ms, total_ms)

        expected = monitor.expected_status
        status_ok = (
            200 <= response.status_code < 300
            if expected == "2xx"
            else response.status_code == int(expected)
        )
        if status_ok:
            return ProbeResult(
                is_up=True,
                status_code=response.status_code,
                response_time_ms=round(total_ms),
                error=None,
                error_kind=None,
                timings=timings_out,
            )
        return ProbeResult(
            is_up=False,
            status_code=response.status_code,
            response_time_ms=round(total_ms),
            error=f"expected status {expected}, got {response.status_code}",
            error_kind="http_status",
            timings=timings_out,
        )

    def _collect_timings(
        self, timings: ConnectTimings, ttfb_ms: float | None, total_ms: float
    ) -> dict:
        values = {
            "dns_ms": timings.dns_ms,
            "connect_ms": timings.connect_ms,
            "tls_ms": timings.tls_ms,
            "ttfb_ms": ttfb_ms,
            "total_ms": total_ms,
        }
        return {key: value for key, value in values.items() if value is not None}

    def _failure(
        self,
        monitor: ClaimedMonitor,
        timings: ConnectTimings,
        t_start: float,
        ttfb_ms: float | None,
        message: str,
        error_kind: str,
    ) -> ProbeResult:
        total_ms = (time.monotonic() - t_start) * 1000
        return ProbeResult(
            is_up=False,
            status_code=None,
            response_time_ms=round(total_ms),
            error=message[:_MAX_ERROR_LENGTH],
            error_kind=error_kind,
            timings=self._collect_timings(timings, ttfb_ms, total_ms),
        )
