"""FR-6.5 daily per-account-per-kind send cap. Checked at delivery time (claim-time deliberately
does not filter on this -- an over-cap account still has its incidents/outbox rows recorded,
only sending is capped), using the ix_notifications_account_id_sent_at index from migration 0011.

This is a check-then-act read with no lock -- explicitly a SOFT cap. Two notifier tasks can both
read "2 of 3 used" and both proceed, overshooting by one. Documented here and in
docs/progress/day-09.md, not a bug: the brief calls for exactly this tradeoff over adding
contention to the hot delivery path for a launch-period abuse limit.
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import Account
from app.plans.config import get_plan

_SENT_TODAY_SQL = text(
    """
    SELECT count(*) FROM notifications n
    JOIN notification_channels c ON c.id = n.channel_id
    WHERE n.account_id = :account_id AND c.kind = :kind AND n.status = 'sent'
      AND n.sent_at >= date_trunc('day', now() AT TIME ZONE 'utc') AT TIME ZONE 'utc'
    """
)


async def is_over_cap(session: AsyncSession, account_id: uuid.UUID, kind: Literal["email", "webhook"]) -> bool:
    plan_name = (
        await session.execute(select(Account.plan).where(Account.id == account_id))
    ).scalar_one()
    plan = get_plan(plan_name)
    limit = plan.alert_emails_per_day if kind == "email" else plan.webhooks_per_day

    sent_today = (
        await session.execute(_SENT_TODAY_SQL, {"account_id": account_id, "kind": kind})
    ).scalar_one()
    return sent_today >= limit
