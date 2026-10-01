from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

import httpx

from bot.callback import create_app
from bot.models.admin_web import AdminLogin, AdminSession
from bot.services.admin_web import AdminWebService


class AdminWebRoutesTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.service = AsyncMock(spec=AdminWebService)
        self.session = AdminSession("amupouya", "csrf-test", datetime.now(UTC) + timedelta(hours=1))
        self.service.login.return_value = AdminLogin("private-session-token", self.session)
        self.service.session.return_value = self.session
        self.app = create_app()
        self.app.state.admin_web_service = self.service
        self.app.state.admin_public_origin = "https://bot.amupouya.org"
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="https://bot.amupouya.org",
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    async def test_admin_page_is_html_with_security_headers_and_no_secrets(self) -> None:
        response = await self.client.get("/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("default-src 'none'", response.headers["content-security-policy"])
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn("no-store", response.headers["cache-control"])
        self.assertNotIn("private-session-token", response.text)

    async def test_login_requires_exact_origin_and_sets_secure_cookie(self) -> None:
        body = {"username": "amupouya", "password": "example-pass"}
        blocked = await self.client.post(
            "/admin/api/login", json=body, headers={"Origin": "https://attacker.example"}
        )
        self.assertEqual(blocked.status_code, 403)
        self.service.login.assert_not_awaited()
        response = await self.client.post(
            "/admin/api/login", json=body, headers={"Origin": "https://bot.amupouya.org"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["csrf"], "csrf-test")
        cookie = response.headers["set-cookie"].lower()
        for flag in ("httponly", "secure", "samesite=strict", "path=/admin"):
            self.assertIn(flag, cookie)

    async def test_auth_and_csrf_guard_plan_updates(self) -> None:
        self.service.session.return_value = None
        denied = await self.client.get("/admin/api/plans")
        self.assertEqual(denied.status_code, 401)
        self.service.session.return_value = self.session
        self.client.cookies.set("papilio_admin_session", "private-session-token", path="/admin")
        body = {"code": "M30", "title": "۳۰ گیگ", "traffic_gb": 30,
                "duration_days": 30, "price_toman": 59000, "sort_order": 1, "emoji": "🦋"}
        without_csrf = await self.client.post(
            "/admin/api/plans", json=body, headers={"Origin": "https://bot.amupouya.org"}
        )
        self.assertEqual(without_csrf.status_code, 403)
        self.service.save_plan.assert_not_awaited()
        wrong_origin = await self.client.post(
            "/admin/api/plans", json=body,
            headers={"Origin": "https://attacker.example", "X-CSRF-Token": "csrf-test"},
        )
        self.assertEqual(wrong_origin.status_code, 403)

    async def test_password_change_needs_csrf_and_clears_cookie(self) -> None:
        self.client.cookies.set("papilio_admin_session", "private-session-token", path="/admin")
        body = {"current_password": "example-pass", "new_password": "a-better-password-123"}
        denied = await self.client.post(
            "/admin/api/password", json=body, headers={"Origin": "https://bot.amupouya.org"}
        )
        self.assertEqual(denied.status_code, 403)
        response = await self.client.post(
            "/admin/api/password", json=body,
            headers={"Origin": "https://bot.amupouya.org", "X-CSRF-Token": "csrf-test"},
        )
        self.assertEqual(response.status_code, 204)
        self.assertIn("max-age=0", response.headers["set-cookie"].lower())
        self.service.change_password.assert_awaited_once_with(
            "amupouya", "example-pass", "a-better-password-123"
        )

    async def test_pricing_settings_are_owner_only_and_use_rial_in_service(self) -> None:
        self.client.cookies.set("papilio_admin_session", "private-session-token", path="/admin")
        self.service.get_pricing.return_value = None
        self.service.list_plans.return_value = []
        read = await self.client.get("/admin/api/pricing")
        self.assertEqual(read.status_code, 200)
        self.assertIsNone(read.json()["assumptions"])
        body = {
            "period_days": 30, "daily_server_cost_toman": 80000,
            "included_traffic_gb": 900, "overage_cost_toman_per_gb": 350,
            "target_customers": 25, "contingency_percent": 10,
            "target_margin_percent": 25,
        }
        denied = await self.client.put(
            "/admin/api/pricing", json=body,
            headers={"Origin": "https://bot.amupouya.org"},
        )
        self.assertEqual(denied.status_code, 403)
        saved = await self.client.put(
            "/admin/api/pricing", json=body,
            headers={"Origin": "https://bot.amupouya.org", "X-CSRF-Token": "csrf-test"},
        )
        self.assertEqual(saved.status_code, 200)
        value = self.service.save_pricing.await_args.args[0]
        self.assertEqual(value.daily_server_cost_rial, 800_000)
        self.assertEqual(value.overage_cost_rial_per_gb, 3_500)

    async def test_readiness_never_claims_live_node(self) -> None:
        self.client.cookies.set("papilio_admin_session", "private-session-token", path="/admin")
        response = await self.client.get("/admin/api/readiness")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["sales_enabled"])
        self.assertFalse(response.json()["live_usage_connected"])
