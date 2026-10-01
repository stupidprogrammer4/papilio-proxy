from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bot.models.access import SubscriptionAccess


@dataclass(frozen=True, slots=True)
class PendingProvision:
    subscription_id: str
    telegram_id: int
    title: str
    traffic_limit_bytes: int
    duration_days: int


@dataclass(frozen=True, slots=True)
class ActiveNodeAccess:
    access: SubscriptionAccess
    title: str


@dataclass(frozen=True, slots=True)
class NodeSnapshot:
    email: str
    uplink_bytes: int
    downlink_bytes: int
    measured_at: datetime
    revoked: bool


@dataclass(frozen=True, slots=True)
class IssuedNodeLinks:
    vless_link: str
    vmess_link: str
    expires_at: datetime
    snapshot: NodeSnapshot
