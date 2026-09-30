from __future__ import annotations

import json
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx

from bot.callback import create_app
from bot.infra.db.credentials import MysqlCredentialVault
from bot.infra.kpay import KpayVerifier
from bot.models.credentials import KpayCredentials
from bot.models.payments import ProviderVerification
from bot.services.payments import PaymentVerificationService


class KpayVerifierTests(IsolatedAsyncioTestCase):
    async def test_login_uses_form_and_verification_uses_bearer_token(self) -> None:
        vault = AsyncMock(spec=MysqlCredentialVault)
        vault.get.return_value = None
        vault.load_kpay_credentials.return_value = KpayCredentials(
            "example-user", "example-password"
        )
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            if request.url.path == "/auth/login":
                self.assertEqual(
                    parse_qs(request.content.decode()),
                    {"username": ["example-user"], "password": ["example-password"]},
                )
                self.assertEqual(
                    request.headers["content-type"], "application/x-www-form-urlencoded"
                )
                return httpx.Response(200, json={"access_token": "test-token"})
            self.assertEqual(request.headers["authorization"], "Bearer test-token")
            self.assertEqual(json.loads(request.content), {"authority": "sample-authority"})
            return httpx.Response(
                200,
                json={
                    "id": "transaction-1",
                    "authority": "sample-authority",
                    "status": "paid",
                    "amount": 50000,
                    "paid_at": "2026-09-30T00:00:00Z",
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await KpayVerifier("https://example.test", vault, client).verify(
                "sample-authority"
            )

        self.assertEqual(seen, ["/auth/login", "/transactions/verify"])
        self.assertTrue(result.verified)
        self.assertEqual(result.amount_rial, 50000)
        vault.save_kpay_tokens.assert_awaited_once_with("test-token", None)

    async def test_unknown_payment_status_fails_closed(self) -> None:
        vault = AsyncMock(spec=MysqlCredentialVault)
        vault.get.return_value = "test-token"

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "id": "transaction-1",
                    "authority": "sample-authority",
                    "status": "pending",
                    "amount": 50000,
                    "paid_at": None,
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await KpayVerifier("https://example.test", vault, client).verify(
                "sample-authority"
            )

        self.assertFalse(result.verified)


class PaymentCallbackTests(IsolatedAsyncioTestCase):
    async def test_callback_requires_one_authority(self) -> None:
        service = AsyncMock(spec=PaymentVerificationService)
        app = create_app(service)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            absent = await client.get("/payments/kpay/callback")
            duplicated = await client.get("/payments/kpay/callback?authority=one&authority=two")
        self.assertEqual(absent.status_code, 400)
        self.assertEqual(duplicated.status_code, 400)
        service.verify_callback.assert_not_awaited()

    async def test_paid_provider_result_does_not_claim_fulfillment(self) -> None:
        service = AsyncMock(spec=PaymentVerificationService)
        service.verify_callback.return_value = ProviderVerification(
            "sample-authority", "paid", "transaction-1", 50000, "2026-09-30T00:00:00Z"
        )
        app = create_app(service)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/payments/kpay/callback?authority=sample-authority")

        self.assertEqual(response.status_code, 200)
        self.assertIn("فعال‌سازی سرویس هنوز بررسی نشده‌اند", response.text)
        service.verify_callback.assert_awaited_once_with("sample-authority")

    async def test_unconfigured_callback_fails_closed(self) -> None:
        app = create_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/payments/kpay/callback?authority=sample-authority")
        self.assertEqual(response.status_code, 503)
