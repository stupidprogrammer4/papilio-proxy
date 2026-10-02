from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase

import httpx

from bot.callback import create_app
from bot.models.access import SubscriptionAccess, UsageAlert
from bot.presentation.subscription_view import connection_links
from bot.services.access import AccessService, AccessUnavailable

USER_ID = "123e4567-e89b-42d3-a456-426614174000"
VLESS = f"vless://{USER_ID}@node.example:443?security=reality#Papilio"
VMESS = "vmess://" + base64.b64encode(
    json.dumps({"id": USER_ID, "add": "node.example"}).encode()
).decode()


class MemoryAccessRepository:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.access = SubscriptionAccess(
            "order-1", 77, "private-token", VLESS, VMESS,
            1000, 100, 50, now + timedelta(days=30), now,
        )
        self.alerts: list[UsageAlert] = []

    async def activate(
        self, subscription_id: str, token: str, vless_link: str,
        vmess_link: str, measured_at: datetime,
    ) -> SubscriptionAccess:
        self.access = replace(
            self.access, subscription_id=subscription_id, token=token,
            vless_link=vless_link, vmess_link=vmess_link,
            uplink_bytes=0, downlink_bytes=0, last_measured_at=measured_at,
        )
        return self.access

    async def get_by_token(self, token: str) -> SubscriptionAccess | None:
        return self.access if token == self.access.token else None

    async def get_for_user(
        self, telegram_id: int, subscription_id: str
    ) -> SubscriptionAccess | None:
        if telegram_id == self.access.telegram_id and subscription_id == self.access.subscription_id:
            return self.access
        return None

    async def record_usage(
        self, subscription_id: str, uplink_bytes: int,
        downlink_bytes: int, measured_at: datetime,
    ) -> bool:
        self.access = replace(
            self.access, uplink_bytes=uplink_bytes,
            downlink_bytes=downlink_bytes, last_measured_at=measured_at,
        )
        return uplink_bytes + downlink_bytes >= self.access.traffic_limit_bytes

    async def claim_alerts(self, limit: int = 20) -> list[UsageAlert]:
        return self.alerts[:limit]

    async def mark_alert_sent(self, alert_id: int) -> None:
        self.alerts = [item for item in self.alerts if item.id != alert_id]

    async def release_alert(self, alert_id: int) -> None:
        pass


class AccessTests(IsolatedAsyncioTestCase):
    async def test_provisioning_requires_two_links_with_same_uuid(self) -> None:
        repository = MemoryAccessRepository()
        service = AccessService(repository)
        with self.assertRaises(AccessUnavailable):
            await service.record_provisioned(
                "order-1", VLESS,
                "vmess://" + base64.b64encode(json.dumps({"id": str(__import__("uuid").uuid4())}).encode()).decode(),
                datetime.now(UTC),
            )
        access = await service.record_provisioned("order-1", VLESS, VMESS, datetime.now(UTC))
        self.assertEqual(access.vless_link, VLESS)
        self.assertEqual(access.vmess_link, VMESS)
        self.assertGreaterEqual(len(access.token), 40)

    async def test_stale_counters_fail_closed(self) -> None:
        repository = MemoryAccessRepository()
        repository.access = replace(
            repository.access, last_measured_at=datetime.now(UTC) - timedelta(minutes=11)
        )
        with self.assertRaises(AccessUnavailable):
            await AccessService(repository).get_by_token("private-token")

    async def test_subscription_returns_both_links_and_usage_header(self) -> None:
        repository = MemoryAccessRepository()
        service = AccessService(repository)
        app = create_app(access_service=service)
        app.state.subscription_public_base_url = "https://sub.example"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://sub.example"
        ) as client:
            response = await client.get("/s/private-token")
            usage = await client.get("/usage/private-token")
            missing = await client.get("/s/not-a-token")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text.splitlines(), connection_links(repository.access))
        title = response.headers["profile-title"].removeprefix("base64:")
        self.assertEqual(base64.b64decode(title).decode(), repository.access.profile_name)
        self.assertIn("upload=100; download=50; total=1000", response.headers["subscription-userinfo"])
        self.assertEqual(response.headers["cache-control"], "private, no-store, max-age=0")
        self.assertIn("/usage/private-token", response.headers["profile-web-page-url"])
        self.assertEqual(usage.status_code, 200)
        self.assertIn("باقیمانده", usage.text)
        self.assertNotIn(VLESS, usage.text)
        self.assertEqual(missing.status_code, 404)

    async def test_profile_url_ignores_untrusted_host_and_expired_access_is_gone(self) -> None:
        repository = MemoryAccessRepository()
        app = create_app(access_service=AccessService(repository))
        app.state.subscription_public_base_url = "https://sub.example"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://sub.example"
        ) as client:
            response = await client.get("/s/private-token", headers={"Host": "attacker.example"})
            repository.access = replace(
                repository.access, expires_at=datetime.now(UTC) - timedelta(seconds=1)
            )
            expired = await client.get("/s/private-token")
        self.assertEqual(
            response.headers["profile-web-page-url"],
            "https://sub.example/usage/private-token",
        )
        self.assertEqual(expired.status_code, 410)
        self.assertNotIn(VLESS, expired.text)

    async def test_stale_subscription_endpoint_does_not_disclose_links(self) -> None:
        repository = MemoryAccessRepository()
        repository.access = replace(
            repository.access, last_measured_at=datetime.now(UTC) - timedelta(hours=1)
        )
        app = create_app(access_service=AccessService(repository))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://sub.example"
        ) as client:
            response = await client.get("/s/private-token")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(VLESS, response.text)
