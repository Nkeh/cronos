"""Plain-English labels for incidents.cause -- the backend mirror of
frontend/src/features/incidents/causeCopy.ts's mapping. Kept here, not imported from anywhere
frontend-side (two separate runtimes), but the two must be kept in lockstep by hand: this is what
makes an alert email's subject line ("DOWN: api — Timed out") read the same way the incident
appears in the UI, instead of leaking a raw error_kind/cause value to an end user.
"""

from __future__ import annotations

CAUSE_COPY: dict[str, str] = {
    "http_status": "Unexpected status code",
    "timeout": "Timed out",
    "connection": "Couldn't connect",
    "dns": "DNS lookup failed",
    "tls": "TLS handshake failed",
    "redirects": "Too many redirects",
    "blocked": "Blocked by security policy",
    "heartbeat_missed": "Missed check-in",
    "heartbeat_fail": "Reported failure",
}


def cause_copy(cause: str | None) -> str:
    if cause is None:
        return "Unknown"
    return CAUSE_COPY.get(cause, cause)
