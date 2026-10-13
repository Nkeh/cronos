"""PLANS — the single source of truth for plan-size limits.

v1 has exactly one plan: 'launch'. No billing, no tiers, no feature gating
(CLAUDE.md). The seam stays from day one: every limit is read through PLANS
(via check_limit/check_interval_minimum, app/plans/dependencies.py), never
hard-coded elsewhere, so v2 can add plans without touching callers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.core.config import ConfigurationError


@dataclass(frozen=True)
class PlanLimits:
    name: str
    max_monitors: int
    max_heartbeats: int
    min_interval_seconds: int
    max_status_pages: int
    private_status_pages: bool
    raw_retention_days: int
    aggregate_retention_days: int
    alert_emails_per_day: int
    webhooks_per_day: int
    max_api_keys: int  # NEW — not in SRS Section 12, flagged as a Day 4 deviation


PLANS: dict[str, PlanLimits] = {
    "launch": PlanLimits(
        name="launch",
        max_monitors=15,
        max_heartbeats=15,
        min_interval_seconds=120,
        max_status_pages=3,
        private_status_pages=True,
        raw_retention_days=14,
        aggregate_retention_days=90,
        alert_emails_per_day=50,
        webhooks_per_day=500,
        max_api_keys=10,
    ),
}

# Must mirror migration 0002's accounts.plan CHECK (plan IN ('launch')). The
# two are independently maintained — there's no way to derive one from the
# other at import time (no DB access during import) — keep them in lockstep
# by hand; this is a recorded Day 4 deviation, not an oversight.
ALLOWED_PLAN_NAMES: frozenset[str] = frozenset({"launch"})


def validate_plans_config(plans: Mapping[str, PlanLimits], allowed: frozenset[str]) -> None:
    if set(plans) != allowed:
        raise ConfigurationError(
            f"PLANS keys {sorted(plans)} must exactly equal {sorted(allowed)}."
        )
    for plan_name, limits in plans.items():
        if limits.name != plan_name:
            raise ConfigurationError(
                f"PLANS['{plan_name}'].name is {limits.name!r}, expected {plan_name!r}."
            )


# Runs at import time, the same "fails at process startup" guarantee
# check_production_guard relies on for its own concerns — a typo'd plan name
# fails before the app ever serves a request.
validate_plans_config(PLANS, ALLOWED_PLAN_NAMES)


def get_plan(name: str) -> PlanLimits:
    try:
        return PLANS[name]
    except KeyError:
        raise RuntimeError(f"Unknown plan {name!r}.") from None
