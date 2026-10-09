from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from src.modules.operations.notifications.domain.context import (
    CheckoutNoticeAction,
    SubscriptionNoticeAction,
)
from src.modules.operations.notifications.domain.dtos import (
    NotificationKind,
    NotificationPolicy,
)


@dataclass(frozen=True, slots=True)
class NotificationAvailability:
    values: NotificationPolicy
    capacity_valid: bool
    outbound_available: bool
    supported_kinds: tuple[NotificationKind, ...]


@dataclass(frozen=True, slots=True)
class NotificationClaim:
    notification_id: int
    claim_token: str
    telegram_id: int
    text: str
    lease_until: datetime
    action: SubscriptionNoticeAction | CheckoutNoticeAction | None = None


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    outcome: Literal["accepted", "retryable", "ambiguous", "rejected"]
    error_code: str | None = None
    message_id: int | None = None
    retry_after_seconds: int | None = None
