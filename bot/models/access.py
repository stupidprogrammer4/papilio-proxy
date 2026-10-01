from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bot.models.subscriptions import SubscriptionStatus


@dataclass(frozen=True, slots=True)
class SubscriptionAccess:
    subscription_id: str
    telegram_id: int
    token: str
    vless_link: str
    vmess_link: str
    traffic_limit_bytes: int
    uplink_bytes: int
    downlink_bytes: int
    expires_at: datetime
    last_measured_at: datetime | None
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE

    @property
    def traffic_used_bytes(self) -> int:
        return self.uplink_bytes + self.downlink_bytes

    @property
    def traffic_remaining_bytes(self) -> int:
        return max(0, self.traffic_limit_bytes - self.traffic_used_bytes)


@dataclass(frozen=True, slots=True)
class UsageAlert:
    id: int
    subscription_id: str
    telegram_id: int
    traffic_used_bytes: int
    traffic_limit_bytes: int


@dataclass(frozen=True, slots=True)
class ProvisionDelivery:
    subscription_id: str
    access: SubscriptionAccess
