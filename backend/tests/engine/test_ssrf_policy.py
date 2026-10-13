from __future__ import annotations

import socket

import pytest

from app.engine import ssrf_policy
from app.engine.ssrf_policy import UrlPolicyError, normalize_and_validate_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://169.254.169.254/latest/meta-data",
        "http://100.64.1.1/",
        "http://172.28.89.10/",
        "http://10.0.0.1/",
        "http://0.0.0.0/",
        "http://localhost:8000/",
        "http://foo.local/",
        "http://chaos/",
    ],
    ids=[
        "loopback_ipv4",
        "loopback_ipv6",
        "ipv4_mapped_ipv6_loopback",
        "metadata_address",
        "shared_address_space",
        "docker_caddy_subnet",
        "rfc1918_private",
        "unspecified_ipv4",
        "localhost_name",
        "dot_local_suffix",
        "single_label_host_not_allow_listed",
    ],
)
def test_host_blocked(url: str) -> None:
    with pytest.raises(UrlPolicyError) as exc_info:
        normalize_and_validate_url(url)
    assert exc_info.value.code == "url_host_blocked"


def test_embedded_credentials_rejected() -> None:
    with pytest.raises(UrlPolicyError) as exc_info:
        normalize_and_validate_url("http://user:pass@example.com/")
    assert exc_info.value.code == "url_credentials"


def test_disallowed_scheme_rejected() -> None:
    with pytest.raises(UrlPolicyError) as exc_info:
        normalize_and_validate_url("ftp://example.com/")
    assert exc_info.value.code == "url_scheme"


@pytest.mark.parametrize("port", [22, 2375, 5432, 6379, 11211], ids=lambda p: f"port_{p}")
def test_denylisted_port_rejected(port: int) -> None:
    with pytest.raises(UrlPolicyError) as exc_info:
        normalize_and_validate_url(f"http://example.com:{port}/")
    assert exc_info.value.code == "url_port_blocked"


def test_accepted_public_https_url() -> None:
    parsed = normalize_and_validate_url("https://example.com/health")
    assert parsed.normalized_url == "https://example.com/health"
    assert parsed.host == "example.com"
    assert parsed.port == 443


def test_dev_allow_host_skips_host_identity_checks() -> None:
    parsed = normalize_and_validate_url("http://chaos:8000/x", allow_hosts=frozenset({"chaos"}))
    assert parsed.host == "chaos"
    assert parsed.normalized_url == "http://chaos:8000/x"


def test_idna_normalizes_non_ascii_host() -> None:
    parsed = normalize_and_validate_url("http://münchen.example/")
    assert parsed.host == "xn--mnchen-3ya.example"


def test_fragment_is_dropped() -> None:
    parsed = normalize_and_validate_url("https://example.com/path#fragment")
    assert "#" not in parsed.normalized_url


def test_url_too_long_is_rejected() -> None:
    with pytest.raises(UrlPolicyError) as exc_info:
        normalize_and_validate_url("https://example.com/" + "a" * 3000)
    assert exc_info.value.code == "url_invalid"


# ---- DNS resolution (async) ----


async def test_dns_resolving_to_private_address_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(host: str) -> list[str]:
        return ["127.0.0.1"]

    monkeypatch.setattr(ssrf_policy, "_resolve", fake_resolve)

    with pytest.raises(UrlPolicyError) as exc_info:
        await ssrf_policy.check_dns_resolves_public("evil.example")
    assert exc_info.value.code == "url_resolves_private"


async def test_dns_resolving_to_public_address_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(ssrf_policy, "_resolve", fake_resolve)
    await ssrf_policy.check_dns_resolves_public("example.com")  # must not raise


async def test_nxdomain_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(host: str) -> list[str]:
        raise socket.gaierror("not found")

    monkeypatch.setattr(ssrf_policy, "_resolve", fake_resolve)
    await ssrf_policy.check_dns_resolves_public("nxdomain.example")  # must not raise


async def test_dns_timeout_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(host: str) -> list[str]:
        raise TimeoutError

    monkeypatch.setattr(ssrf_policy, "_resolve", fake_resolve)
    await ssrf_policy.check_dns_resolves_public("slow.example")  # must not raise


async def test_dev_allow_host_skips_dns_entirely(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_if_called(host: str) -> list[str]:
        raise AssertionError("must not call DNS for an allow-listed host")

    monkeypatch.setattr(ssrf_policy, "_resolve", fail_if_called)
    await ssrf_policy.check_dns_resolves_public("chaos", allow_hosts=frozenset({"chaos"}))
