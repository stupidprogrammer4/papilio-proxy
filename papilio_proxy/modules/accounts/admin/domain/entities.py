from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AdminSession:
    username: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AdminLogin:
    token: str
    session: AdminSession


@dataclass(frozen=True, slots=True)
class AdminUserRow:
    telegram_id: int
    display_name: str
    username: str | None
    subscriptions: int
    created_at: datetime
    is_blocked: bool = False
    block_reason: str = ""


@dataclass(frozen=True, slots=True)
class AdminOrderRow:
    id: str
    telegram_id: int
    plan_code: str
    status: str
    price_rial: int
    traffic_limit_bytes: int
    traffic_used_bytes: int
    created_at: datetime
    expires_at: datetime | None
    payment_status: str | None
    is_blocked: bool = False


@dataclass(frozen=True, slots=True)
class AdminFinancialSnapshot:
    settled_count: int
    settled_amount_rial: int
    pending_count: int


class AdminLoginDenied(PermissionError):
    """Invalid credentials or a temporarily locked admin account."""
