from __future__ import annotations

import base64
import binascii
import json
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

from bot.models.access import SubscriptionAccess, UsageAlert


class AccessUnavailable(RuntimeError):
    """A subscription must not be delivered with missing or stale counters."""


class AccessInactive(AccessUnavailable):
    """The entitlement has expired or exhausted its quota."""


class UsageStale(AccessUnavailable):
    """The last trustworthy counter reading is too old."""


class AccessRepository(Protocol):
    async def activate(
        self, subscription_id: str, token: str, vless_link: str, vmess_link: str,
        measured_at: datetime,
    ) -> SubscriptionAccess: ...

    async def get_by_token(self, token: str) -> SubscriptionAccess | None: ...

    async def get_for_user(self, telegram_id: int, subscription_id: str) -> SubscriptionAccess | None: ...

    async def record_usage(
        self, subscription_id: str, uplink_bytes: int, downlink_bytes: int,
        measured_at: datetime,
    ) -> bool: ...

    async def claim_alerts(self, limit: int = 20) -> list[UsageAlert]: ...

    async def mark_alert_sent(self, alert_id: int) -> None: ...

    async def release_alert(self, alert_id: int) -> None: ...


def _link_user_id(vless_link: str, vmess_link: str) -> None:
    try:
        vless = urlsplit(vless_link)
        if vless.scheme != "vless" or vless.username is None or not vless.hostname:
            raise ValueError
        vless_id = UUID(vless.username)
        vmess = urlsplit(vmess_link)
        if vmess.scheme != "vmess" or not vmess.netloc:
            raise ValueError
        payload = json.loads(base64.b64decode(vmess.netloc, validate=True))
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("id"), str)
            or UUID(payload["id"]) != vless_id
        ):
            raise ValueError
    except (ValueError, KeyError, TypeError, UnicodeError, binascii.Error) as exc:
        raise AccessUnavailable("Connection links are invalid or do not share one user") from exc


@dataclass(slots=True)
class AccessService:
    repository: AccessRepository
    max_counter_age: timedelta = timedelta(minutes=10)
    node_links: Callable[[str], Awaitable[str | None]] | None = None

    async def record_provisioned(
        self, subscription_id: str, vless_link: str, vmess_link: str,
        measured_at: datetime,
    ) -> SubscriptionAccess:
        """Call only after both Xray users were applied and zero counters were read."""
        _link_user_id(vless_link, vmess_link)
        now = datetime.now(UTC)
        if (
            measured_at.tzinfo is None
            or measured_at > now + timedelta(seconds=30)
            or now - measured_at > self.max_counter_age
        ):
            raise AccessUnavailable("Invalid or stale initial counter timestamp")
        token = secrets.token_urlsafe(32)
        return await self.repository.activate(
            subscription_id, token, vless_link, vmess_link, measured_at
        )

    async def get_by_token(self, token: str) -> SubscriptionAccess | None:
        if not token or len(token) > 128:
            return None
        access = await self.repository.get_by_token(token)
        self._require_current(access)
        return await self._decorate(access)

    async def get_for_user(
        self, telegram_id: int, subscription_id: str
    ) -> SubscriptionAccess | None:
        access = await self.repository.get_for_user(telegram_id, subscription_id)
        self._require_current(access)
        return await self._decorate(access)

    async def _decorate(self, access: SubscriptionAccess | None) -> SubscriptionAccess | None:
        if access is None or self.node_links is None:
            return access
        try:
            link = await self.node_links(access.subscription_id)
        except RuntimeError as exc:
            raise AccessUnavailable("Connection metadata is unavailable") from exc
        if link:
            parsed = urlsplit(link)
            if (
                parsed.scheme not in {"hysteria2", "hy2"} or not parsed.hostname
                or parsed.username != access.subscription_id
            ):
                raise AccessUnavailable("Hysteria link does not share the entitlement")
        return replace(access, hysteria_link=link)

    async def record_usage(
        self, subscription_id: str, uplink_bytes: int, downlink_bytes: int,
        measured_at: datetime,
    ) -> bool:
        if (
            isinstance(uplink_bytes, bool) or isinstance(downlink_bytes, bool)
            or uplink_bytes < 0 or downlink_bytes < 0 or measured_at.tzinfo is None
            or measured_at > datetime.now(UTC) + timedelta(seconds=30)
        ):
            raise AccessUnavailable("Invalid usage reading")
        return await self.repository.record_usage(
            subscription_id, uplink_bytes, downlink_bytes, measured_at
        )

    def _require_current(self, access: SubscriptionAccess | None) -> None:
        if access is None:
            return
        now = datetime.now(UTC)
        if (
            access.status.value != "active" or access.expires_at <= now
            or access.traffic_used_bytes >= access.traffic_limit_bytes
        ):
            raise AccessInactive("Subscription expired or quota exhausted")
        if (
            access.last_measured_at is None
            or now - access.last_measured_at > self.max_counter_age
            or access.last_measured_at > now + timedelta(seconds=30)
        ):
            raise UsageStale("Subscription usage is stale")
