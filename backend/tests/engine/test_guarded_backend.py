"""Unit tests for the connect-time SSRF guard, against fake resolvers/connectors -- no real
network or DB. Covers CLAUDE.md's required SSRF test list at the connect-time layer: decimal
and octal IP forms, IPv6 loopback, a DNS name resolving to a private address, a mixed
public/private record set, and DNS rebinding."""

from __future__ import annotations

import socket

import httpcore
import pytest

from app.engine.guarded_backend import (
    BlockedAddressError,
    ConnectTimings,
    DnsResolutionError,
    GuardedBackend,
)


class _FakeStream(httpcore.AsyncNetworkStream):
    def __init__(self) -> None:
        self.start_tls_calls: list[dict] = []

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return b""

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.start_tls_calls.append({"server_hostname": server_hostname})
        return self

    def get_extra_info(self, info: str):
        return None


class _FakeInnerBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, *, stream: _FakeStream | None = None) -> None:
        self.connect_calls: list[tuple[str, int]] = []
        self._stream = stream or _FakeStream()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.connect_calls.append((host, port))
        return self._stream

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise NotImplementedError


def _resolver(addresses: list[str]):
    async def _resolve(host: str) -> list[str]:
        return addresses

    return _resolve


def _failing_resolver(exc: Exception):
    async def _resolve(host: str) -> list[str]:
        raise exc

    return _resolve


def _make_backend(*, resolve=None, allow_hosts=frozenset(), inner=None) -> tuple[GuardedBackend, ConnectTimings]:
    timings = ConnectTimings()
    kwargs = {"timings": timings, "allow_hosts": allow_hosts, "inner_backend": inner}
    if resolve is not None:
        kwargs["resolve"] = resolve
    backend = GuardedBackend(**kwargs)
    return backend, timings


async def test_ip_literal_loopback_blocked() -> None:
    backend, _ = _make_backend()
    with pytest.raises(BlockedAddressError):
        await backend.connect_tcp("127.0.0.1", 443)


@pytest.mark.parametrize(
    "host",
    ["2130706433", "0177.0.0.1", "0x7f.0.0.1", "017700000001"],
    ids=["decimal", "octal_dotted", "hex_dotted", "octal_plain"],
)
async def test_decimal_octal_hex_ip_forms_block_via_dns_fallthrough(host: str) -> None:
    """None of these parse as ipaddress literals in Python (verified empirically), so they fall
    through to the DNS-resolution branch. The real attack this defends against is a resolver
    (glibc's getaddrinfo, in production) accepting a lenient numeric form and handing back the
    loopback address anyway -- which is exactly what the fake resolver simulates here."""
    inner = _FakeInnerBackend()
    backend, _ = _make_backend(resolve=_resolver(["127.0.0.1"]), inner=inner)
    with pytest.raises(BlockedAddressError):
        await backend.connect_tcp(host, 443)
    assert inner.connect_calls == []


async def test_ipv6_loopback_blocked() -> None:
    backend, _ = _make_backend()
    with pytest.raises(BlockedAddressError):
        await backend.connect_tcp("::1", 443)


async def test_ipv4_mapped_ipv6_loopback_blocked() -> None:
    backend, _ = _make_backend()
    with pytest.raises(BlockedAddressError):
        await backend.connect_tcp("::ffff:127.0.0.1", 443)


async def test_metadata_address_literal_blocked() -> None:
    backend, _ = _make_backend()
    with pytest.raises(BlockedAddressError):
        await backend.connect_tcp("169.254.169.254", 80)


async def test_metadata_address_via_dns_blocked() -> None:
    inner = _FakeInnerBackend()
    backend, _ = _make_backend(resolve=_resolver(["169.254.169.254"]), inner=inner)
    with pytest.raises(BlockedAddressError):
        await backend.connect_tcp("evil.example", 80)
    assert inner.connect_calls == []


async def test_fake_resolver_all_private_blocks() -> None:
    inner = _FakeInnerBackend()
    backend, _ = _make_backend(resolve=_resolver(["10.0.0.5"]), inner=inner)
    with pytest.raises(BlockedAddressError):
        await backend.connect_tcp("evil.example", 443)
    assert inner.connect_calls == []


async def test_mixed_public_and_private_record_set_blocks_entirely() -> None:
    """The core all-or-nothing proof: one private address anywhere in the resolved set blocks
    the whole connect, and the inner connector is never reached -- no cherry-picking "the good
    one" out of a mixed record set."""
    inner = _FakeInnerBackend()
    backend, _ = _make_backend(resolve=_resolver(["93.184.216.34", "10.0.0.5"]), inner=inner)
    with pytest.raises(BlockedAddressError):
        await backend.connect_tcp("mixed.example", 443)
    assert inner.connect_calls == []


async def test_all_public_resolved_set_connects_to_resolved_ip_not_hostname() -> None:
    """DNS-rebinding defense proof: the inner connector receives the already-resolved IP, never
    the original hostname -- there is no second lookup left for a rebinding attack to exploit."""
    inner = _FakeInnerBackend()
    backend, _ = _make_backend(resolve=_resolver(["93.184.216.34"]), inner=inner)
    stream = await backend.connect_tcp("good.example", 443)
    assert inner.connect_calls == [("93.184.216.34", 443)]
    assert stream is not None


async def test_resolver_called_exactly_once_per_connect() -> None:
    calls: list[str] = []

    async def counting_resolve(host: str) -> list[str]:
        calls.append(host)
        return ["93.184.216.34"]

    inner = _FakeInnerBackend()
    backend, _ = _make_backend(resolve=counting_resolve, inner=inner)
    await backend.connect_tcp("good.example", 443)
    assert calls == ["good.example"]


async def test_dns_timeout_raises_dns_resolution_error() -> None:
    backend, _ = _make_backend(resolve=_failing_resolver(TimeoutError()))
    with pytest.raises(DnsResolutionError):
        await backend.connect_tcp("slow.example", 443)


async def test_dns_nxdomain_raises_dns_resolution_error() -> None:
    backend, _ = _make_backend(resolve=_failing_resolver(socket.gaierror("not found")))
    with pytest.raises(DnsResolutionError):
        await backend.connect_tcp("nxdomain.example", 443)


async def test_allow_hosts_skips_host_identity_but_not_port() -> None:
    inner = _FakeInnerBackend()
    backend, _ = _make_backend(
        resolve=_resolver(["10.0.0.5"]), allow_hosts=frozenset({"chaos"}), inner=inner
    )
    stream = await backend.connect_tcp("chaos", 8000)
    assert inner.connect_calls == [("10.0.0.5", 8000)]
    assert stream is not None

    with pytest.raises(BlockedAddressError):
        await backend.connect_tcp("chaos", 5432)


async def test_denylisted_port_blocked_even_for_public_host() -> None:
    inner = _FakeInnerBackend()
    backend, _ = _make_backend(resolve=_resolver(["93.184.216.34"]), inner=inner)
    with pytest.raises(BlockedAddressError):
        await backend.connect_tcp("good.example", 5432)
    assert inner.connect_calls == []


async def test_start_tls_receives_original_hostname_not_resolved_ip() -> None:
    """SNI/cert-hostname proof without a real handshake: the fake inner stream's start_tls
    records the server_hostname it was called with by httpcore's own connection layer. Here we
    drive it directly against the stream our backend returns, simulating what
    AsyncHTTPConnection._connect does after connect_tcp."""
    inner_stream = _FakeStream()
    inner = _FakeInnerBackend(stream=inner_stream)
    backend, _ = _make_backend(resolve=_resolver(["93.184.216.34"]), inner=inner)
    stream = await backend.connect_tcp("good.example", 443)
    await stream.start_tls(ssl_context=None, server_hostname="good.example")
    assert inner_stream.start_tls_calls == [{"server_hostname": "good.example"}]


async def test_timings_sink_records_dns_and_connect_ms() -> None:
    import asyncio

    async def slow_resolve(host: str) -> list[str]:
        await asyncio.sleep(0.05)
        return ["93.184.216.34"]

    class _SlowInner(_FakeInnerBackend):
        async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            await asyncio.sleep(0.05)
            return await super().connect_tcp(host, port, timeout, local_address, socket_options)

    backend, timings = _make_backend(resolve=slow_resolve, inner=_SlowInner())
    await backend.connect_tcp("good.example", 443)
    assert timings.dns_ms is not None and timings.dns_ms >= 40
    assert timings.connect_ms is not None and timings.connect_ms >= 40


async def test_connect_unix_socket_not_implemented() -> None:
    backend, _ = _make_backend()
    with pytest.raises(NotImplementedError):
        await backend.connect_unix_socket("/tmp/whatever")
