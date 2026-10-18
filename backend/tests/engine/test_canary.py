from __future__ import annotations

import pytest

from app.engine import canary as canary_module
from app.engine.canary import CanaryTracker, run_canary_round
from app.engine.claim import ClaimedMonitor
from app.engine.probe import ProbeResult


class _FakeProbe:
    """Keyed by the url it's given -- run_canary_round builds a throwaway ClaimedMonitor per
    configured URL, so this double reads .url back off it to decide the outcome."""

    def __init__(self, outcomes: dict[str, bool]) -> None:
        self._outcomes = outcomes

    async def check(self, monitor: ClaimedMonitor) -> ProbeResult:
        is_up = self._outcomes[monitor.url]
        return ProbeResult(
            is_up=is_up,
            status_code=200 if is_up else 503,
            response_time_ms=5,
            error=None if is_up else "down",
        )


async def test_zero_of_three_failures_is_healthy() -> None:
    probe = _FakeProbe({"a": True, "b": True, "c": True})
    assert await run_canary_round(probe, ["a", "b", "c"]) is True


async def test_one_of_three_failures_is_healthy() -> None:
    probe = _FakeProbe({"a": False, "b": True, "c": True})
    assert await run_canary_round(probe, ["a", "b", "c"]) is True


async def test_two_of_three_failures_is_degraded() -> None:
    probe = _FakeProbe({"a": False, "b": False, "c": True})
    assert await run_canary_round(probe, ["a", "b", "c"]) is False


async def test_three_of_three_failures_is_degraded() -> None:
    probe = _FakeProbe({"a": False, "b": False, "c": False})
    assert await run_canary_round(probe, ["a", "b", "c"]) is False


async def test_no_urls_configured_is_trivially_healthy() -> None:
    probe = _FakeProbe({})
    assert await run_canary_round(probe, []) is True


def test_tracker_logs_only_on_transition(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[str] = []
    infos: list[str] = []
    monkeypatch.setattr(
        canary_module.logger, "warning", lambda event, **kw: warnings.append(event)
    )
    monkeypatch.setattr(canary_module.logger, "info", lambda event, **kw: infos.append(event))

    tracker = CanaryTracker()
    assert tracker.ok is True

    tracker.update(True)  # still healthy -- no transition, nothing logged
    assert warnings == [] and infos == []

    tracker.update(False)  # healthy -> degraded
    assert tracker.ok is False
    assert warnings.count("canary_degraded") == 1

    tracker.update(False)  # still degraded -- no re-log
    assert warnings.count("canary_degraded") == 1

    tracker.update(True)  # degraded -> recovered
    assert tracker.ok is True
    assert infos.count("canary_recovered") == 1
