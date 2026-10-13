from __future__ import annotations

import pytest

from app.core.config import ConfigurationError
from app.plans.config import ALLOWED_PLAN_NAMES, PLANS, PlanLimits, validate_plans_config


def _plan(name: str = "launch") -> PlanLimits:
    return PlanLimits(
        name=name,
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
    )


def test_unknown_plan_name_fails_validation() -> None:
    plans = {"launch": _plan(), "lnch": _plan("lnch")}
    with pytest.raises(ConfigurationError, match="PLANS keys"):
        validate_plans_config(plans, frozenset({"launch"}))


def test_missing_plan_fails_validation() -> None:
    with pytest.raises(ConfigurationError, match="PLANS keys"):
        validate_plans_config({}, frozenset({"launch"}))


def test_mismatched_name_field_fails_validation() -> None:
    plans = {"launch": _plan(name="not-launch")}
    with pytest.raises(ConfigurationError, match="expected 'launch'"):
        validate_plans_config(plans, frozenset({"launch"}))


def test_matching_plan_set_passes() -> None:
    validate_plans_config({"launch": _plan()}, frozenset({"launch"}))


def test_real_plans_config_is_valid_at_import() -> None:
    # Importing app.plans.config already ran this at module load — this test
    # just makes that startup guarantee explicit and re-checkable.
    assert set(PLANS) == ALLOWED_PLAN_NAMES == {"launch"}
