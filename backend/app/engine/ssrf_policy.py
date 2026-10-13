"""Save-time URL / SSRF policy — pure functions, no DB access.

Save-time validation here is UX only (CLAUDE.md / SRS Section 13): the
authoritative enforcement happens at connect time inside the custom httpcore
network backend built on Day 7, which is meant to reuse these same functions
(or their connect-time equivalents) rather than duplicate the rules.

Host-identity checks (blocklist/single-label/IP-global) are skippable for a
host listed in `allow_hosts` (the dev-only SSRF_ALLOW_HOSTS escape hatch, e.g.
"chaos"); scheme/credentials/port/length rules are never skippable, even for
an allow-listed host.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

import anyio
import idna

MAX_URL_LENGTH = 2048
ALLOWED_SCHEMES = frozenset({"http", "https"})
_DEFAULT_PORT_BY_SCHEME = {"http": 80, "https": 443}
PORT_DENYLIST = frozenset({2375, 5432, 6379, 11211})
DNS_TIMEOUT_SECONDS = 3

# Denied regardless of ipaddress.is_global's own answer — some of these
# (100.64.0.0/10 in particular) Python's ipaddress module does NOT treat as
# non-global on its own, per SRS Section 13.
_EXTRA_DENIED_NETWORKS = (
    ipaddress.ip_network("169.254.169.254/32"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("172.28.89.0/24"),
)

_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal")


class UrlPolicyError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ParsedUrl:
    normalized_url: str
    host: str
    port: int


def _is_blocked_host_name(host: str) -> bool:
    return host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES)


def _is_single_label(host: str) -> bool:
    return "." not in host


def _unwrap_ipv4_mapped(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _is_denied_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    ip = _unwrap_ipv4_mapped(ip)
    if not ip.is_global:
        return True
    return any(
        ip in network for network in _EXTRA_DENIED_NETWORKS if ip.version == network.version
    )


def _parse_ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def normalize_and_validate_url(
    raw: str, *, allow_hosts: frozenset[str] = frozenset()
) -> ParsedUrl:
    candidate = raw.strip()
    if not candidate or len(candidate) > MAX_URL_LENGTH:
        raise UrlPolicyError("url_invalid", "URL is invalid or too long.")

    parts = urlsplit(candidate)
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UrlPolicyError("url_scheme", "Only http and https URLs are allowed.")
    if parts.username is not None or parts.password is not None:
        raise UrlPolicyError(
            "url_credentials", "URLs with embedded credentials are not allowed."
        )

    host_raw = parts.hostname  # urlsplit already lowercases this
    if not host_raw:
        raise UrlPolicyError("url_invalid", "URL has no host.")

    ip_literal = _parse_ip_literal(host_raw)
    if ip_literal is not None:
        host = str(ip_literal)
    else:
        try:
            host = idna.encode(host_raw).decode("ascii")
        except idna.IDNAError:
            raise UrlPolicyError("url_invalid", "URL host is not a valid hostname.") from None

    port = parts.port if parts.port is not None else _DEFAULT_PORT_BY_SCHEME[scheme]
    if port in PORT_DENYLIST or not (port in (80, 443) or 1024 <= port <= 65535):
        raise UrlPolicyError("url_port_blocked", "This port is not allowed.")

    if host not in allow_hosts:
        if ip_literal is not None:
            if _is_denied_ip(ip_literal):
                raise UrlPolicyError("url_host_blocked", "This host is not allowed.")
        elif _is_blocked_host_name(host) or _is_single_label(host):
            raise UrlPolicyError("url_host_blocked", "This host is not allowed.")

    normalized = f"{scheme}://{host}"
    if parts.port is not None:
        normalized += f":{port}"
    normalized += parts.path or "/"
    if parts.query:
        normalized += f"?{parts.query}"
    # Fragment is deliberately dropped.

    return ParsedUrl(normalized_url=normalized, host=host, port=port)


async def _resolve(host: str) -> list[str]:
    """Indirection so tests monkeypatch this directly instead of stdlib socket."""

    def _getaddrinfo() -> list[str]:
        infos = socket.getaddrinfo(host, None)
        return [info[4][0] for info in infos]

    return await anyio.to_thread.run_sync(_getaddrinfo)


async def check_dns_resolves_public(
    host: str, *, allow_hosts: frozenset[str] = frozenset()
) -> None:
    """NXDOMAIN or timeout -> allow: DNS hiccups must never block users; the
    monitor will simply show a dns failure once probes run (Day 7)."""
    if host in allow_hosts:
        return

    try:
        with anyio.fail_after(DNS_TIMEOUT_SECONDS):
            addresses = await _resolve(host)
    except (socket.gaierror, TimeoutError, OSError):
        return

    for address in addresses:
        ip = _parse_ip_literal(address)
        if ip is not None and _is_denied_ip(ip):
            raise UrlPolicyError(
                "url_resolves_private", "This URL resolves to a private address."
            )
