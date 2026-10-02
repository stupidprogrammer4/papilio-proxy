from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Protocol(StrEnum):
    VMESS = "vmess"
    VLESS = "vless"
    BOTH = "both"


class SubscriptionStatus(StrEnum):
    PENDING_PAYMENT = "pending_payment"
    PAID_AWAITING_PROVISIONING = "paid_awaiting_provisioning"
    TEST_AWAITING_PROVISIONING = "test_awaiting_provisioning"
    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDED = "suspended"


@dataclass(frozen=True, slots=True)
class Plan:
    code: str
    title: str
    traffic_gb: int
    duration_days: int
    price_rial: int
    is_active: bool = True
    sort_order: int = 0
    emoji: str = "🦋"

    def __post_init__(self) -> None:
        if (
            self.traffic_gb <= 0
            or self.duration_days <= 0
            or self.price_rial <= 0
            or self.price_rial % 10 != 0
        ):
            raise ValueError("Plan prices must be positive and divisible by ten rials")

    @property
    def price_toman(self) -> int:
        return self.price_rial // 10

    @property
    def traffic_bytes(self) -> int:
        return self.traffic_gb * 1024**3


@dataclass(frozen=True, slots=True)
class TelegramUser:
    telegram_id: int
    display_name: str
    username: str | None


@dataclass(frozen=True, slots=True)
class Subscription:
    id: str
    telegram_id: int
    plan_code: str
    protocol: Protocol
    status: SubscriptionStatus
    traffic_limit_bytes: int
    traffic_used_bytes: int
    expires_at: datetime | None
    created_at: datetime
    price_rial: int = 0
    duration_days: int = 0

    @property
    def traffic_remaining_bytes(self) -> int:
        return max(0, self.traffic_limit_bytes - self.traffic_used_bytes)


class UnknownPlanError(ValueError):
    """Raised when a requested plan does not exist or is unavailable."""
