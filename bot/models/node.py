from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PendingProvision:
    subscription_id: str
    telegram_id: int
    title: str
    traffic_limit_bytes: int
    duration_days: int


@dataclass(frozen=True, slots=True)
class NodeAccount:
    """Only the counters and limits needed by the frequent node sync."""

    subscription_id: str
    traffic_limit_bytes: int
    uplink_bytes: int
    downlink_bytes: int
    expires_at: datetime
    last_measured_at: datetime | None


@dataclass(frozen=True, slots=True)
class ActiveNodeAccess:
    access: NodeAccount
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
