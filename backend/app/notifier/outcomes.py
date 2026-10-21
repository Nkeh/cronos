"""The shared result shape every delivery path (email, webhook) reduces to, so the claim/record
loop in app/notifier/__main__.py never needs to know which kind of channel it just delivered to.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Outcome = Literal["sent", "retry", "failed", "suppressed"]


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    outcome: Outcome
    status_code: int | None = None
    error: str | None = None
    # Webhook 429s only; None means "use the normal backoff schedule instead".
    retry_after_seconds: int | None = None
