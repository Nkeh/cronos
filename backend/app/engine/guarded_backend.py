"""Connect-time SSRF guard: a custom httpcore async network backend.

Enforces the Day 4 SSRF policy (app.engine.ssrf_policy) at the moment a TCP connection is
actually opened. This is the only point that's immune to DNS rebinding (the address validated
here is the exact address dialed, with no window for a second lookup to answer differently) and
that automatically covers every redirect hop (httpcore calls connect_tcp() again for each hop's
new Origin -- no special-casing needed). Save-time validation in ssrf_policy.py is UX only;
this is the authoritative enforcement, for monitors and (later, Day 9) webhooks alike.

Reuses ssrf_policy's pure functions rather than duplicating the rules, per that module's own
docstring.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable

import anyio
import httpcore

from app.engine import ssrf_policy


class BlockedAddressError(Exception):
    """Raised from connect_tcp when the host (or any resolved address) fails the SSRF policy.

    Deliberately NOT an httpcore exception subclass: httpx's exception-mapping context manager
    (httpx._transports.default.map_httpcore_exceptions) only rewraps exceptions that are
    instances of a fixed set of httpcore types, so this passes through unchanged and lets
    HttpProbe tell "we blocked this" apart from a real network failure with no string matching.
    """

    def __init__(self, host: str, message: str) -> None:
        super().__init__(message)
        self.host = host


class DnsResolutionError(Exception):
    """Raised from connect_tcp on DNS timeout/failure. Also not httpcore-mapped, for the same
    reason -- this is how error_kind="dns" is told apart from error_kind="connection"."""


@dataclass
class ConnectTimings:
    """Mutable sink HttpProbe owns and hands to the backend for exactly one check. Not
    task-safe by design -- a fresh GuardedBackend is built per check (fresh connection per
    check, see http_probe.py), so there's never concurrent access to one instance."""

    dns_ms: float | None = None
    connect_ms: float | None = None
    tls_ms: float | None = None


class _TimedStream(httpcore.AsyncNetworkStream):
    """Wraps the real stream purely to time start_tls. Every other method delegates straight
    through unchanged -- TLS correctness itself (certificate verification, SNI) is entirely the
    real stream's behavior; this adds nothing but a stopwatch."""

    def __init__(self, inner: httpcore.AsyncNetworkStream, timings: ConnectTimings) -> None:
        self._inner = inner
        self._timings = timings

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return await self._inner.read(max_bytes, timeout)

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        await self._inner.write(buffer, timeout)

    async def aclose(self) -> None:
        await self._inner.aclose()

    def get_extra_info(self, info: str) -> Any:
        return self._inner.get_extra_info(info)

    async def start_tls(
        self,
        ssl_context: Any,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.AsyncNetworkStream:
        start = time.monotonic()
        new_inner = await self._inner.start_tls(ssl_context, server_hostname, timeout)
        self._timings.tls_ms = (time.monotonic() - start) * 1000
        # Stay wrapped in case anything downstream re-enters start_tls on the new stream.
        return _TimedStream(new_inner, self._timings)


class GuardedBackend(httpcore.AsyncNetworkBackend):
    """Validates every address at connect time before dialing it, then connects directly to
    the validated IP literal -- never back to the hostname. That's the entire DNS-rebinding
    defense: the address checked is the exact address dialed.
    """

    def __init__(
        self,
        *,
        timings: ConnectTimings,
        allow_hosts: frozenset[str] = frozenset(),
        resolve: Callable[[str], Awaitable[list[str]]] = ssrf_policy.resolve,
        inner_backend: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._timings = timings
        self._allow_hosts = allow_hosts
        self._resolve = resolve  # test seam: fake resolver
        self._inner = inner_backend or httpcore.AnyIOBackend()  # test seam: fake connector

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        # Port policy, defense in depth -- already checked at save time, enforced again here
        # for every connection, not trusted from the saved row alone.
        if port in ssrf_policy.PORT_DENYLIST or not (port in (80, 443) or 1024 <= port <= 65535):
            raise BlockedAddressError(host, f"port {port} is not allowed")

        literal = ssrf_policy.parse_ip_literal(host)
        if literal is not None:
            # host is already an IP literal -- true on any redirect hop that redirects
            # straight to an address, e.g. a 302 to http://169.254.169.254/.
            if host not in self._allow_hosts and ssrf_policy.is_denied_ip(literal):
                raise BlockedAddressError(host, f"{host} is not a routable address")
            target_ip = str(literal)
        else:
            start = time.monotonic()
            try:
                with anyio.fail_after(ssrf_policy.DNS_TIMEOUT_SECONDS):
                    addresses = await self._resolve(host)
            except (socket.gaierror, TimeoutError, OSError) as exc:
                raise DnsResolutionError(f"DNS resolution failed for {host}") from exc
            finally:
                self._timings.dns_ms = (time.monotonic() - start) * 1000

            # All-or-nothing: if ANY resolved address is denied, reject the whole connect --
            # never cherry-pick a "good" address out of a mixed record set. An attacker who
            # gets even one private address into the answer set must not be able to rely on
            # Cronos picking "the other, public-looking one."
            if host not in self._allow_hosts:
                parsed = [ssrf_policy.parse_ip_literal(addr) for addr in addresses]
                if any(ip is not None and ssrf_policy.is_denied_ip(ip) for ip in parsed):
                    raise BlockedAddressError(
                        host, f"{host} resolves to a non-routable address"
                    )
            # Prefer IPv4 if present. A documented choice, not a security property -- both
            # families are validated identically above.
            target_ip = next((addr for addr in addresses if ":" not in addr), addresses[0])

        # Connect directly to the validated IP, never back to the hostname -- anyio's
        # connect_tcp does not re-resolve an IP-literal remote_host, so this is the point where
        # DNS rebinding is closed off: no second lookup can answer differently from this one.
        start = time.monotonic()
        stream = await self._inner.connect_tcp(
            target_ip,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )
        self._timings.connect_ms = (time.monotonic() - start) * 1000
        return _TimedStream(stream, self._timings)

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise NotImplementedError("monitors never use unix sockets")
