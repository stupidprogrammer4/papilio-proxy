from datetime import datetime
from typing import Protocol

from papilio_proxy.modules.network.subscriptions.domain.entities import (
    SubscriptionAccess,
    UsageAlert,
)


class AccessRepository(Protocol):
    async def activate(
        self,
        subscription_id: str,
        token: str,
        vless_link: str,
        vmess_link: str,
        measured_at: datetime,
    ) -> SubscriptionAccess: ...

    async def get_by_token(self, token: str) -> SubscriptionAccess | None: ...

    async def get_for_user(
        self, telegram_id: int, subscription_id: str
    ) -> SubscriptionAccess | None: ...

    async def record_usage(
        self,
        subscription_id: str,
        uplink_bytes: int,
        downlink_bytes: int,
        measured_at: datetime,
    ) -> bool: ...

    async def claim_alerts(self, limit: int = 20) -> list[UsageAlert]: ...

    async def mark_alert_sent(self, alert_id: int) -> None: ...

    async def release_alert(self, alert_id: int) -> None: ...


class TestGrantRepository(Protocol):
    async def grant(self, telegram_id: int, quota_bytes: int, duration_days: int) -> str: ...
