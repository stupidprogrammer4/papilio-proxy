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
from bot.models.payments import PaymentProviderUnavailable
from bot.services.payments import CallbackOutcome, PaymentVerificationService


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

    async def test_checkout_uses_rial_amount_and_order_reference(self) -> None:
        vault = AsyncMock(spec=MysqlCredentialVault)
        vault.get.return_value = "test-token"

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/v1/transactions/create")
            self.assertEqual(request.headers["authorization"], "Bearer test-token")
            payload = json.loads(request.content)
            self.assertEqual(payload["amount"], 590_000)
            self.assertEqual(payload["factor_number"], "order-123")
            self.assertEqual(payload["fee_side"], "seller")
            return httpx.Response(
                200,
                json={
                    "id": "transaction-123",
                    "authority": "authority-123",
                    "amount": 590_000,
                    "status": "pending",
                    "payment_url": "https://kpay.website/transactions/payment/authority-123",
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            checkout = await KpayVerifier("https://kpay.website/api/v1", vault, client).create_transaction(
                shop_id="11111111-1111-4111-8111-111111111111",
                card_id="22222222-2222-4222-8222-222222222222",
                amount_rial=590_000,
                callback_url="https://bot.amupouya.org/payments/kpay/callback",
                order_id="order-123",
                description="Papilio plan",
            )
        self.assertEqual(checkout.authority, "authority-123")
        self.assertEqual(checkout.amount_rial, 590_000)

    async def test_live_card_response_without_url_checks_public_record(self) -> None:
        vault = AsyncMock(spec=MysqlCredentialVault)
        vault.get.return_value = "test-token"
        requests: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request.url.path)
            if request.method == "POST":
                self.assertEqual(json.loads(request.content)["fee_side"], "seller")
                return httpx.Response(
                    201,
                    json={
                        "id": "transaction-123", "authority": "authority-123",
                        "amount": 590_000, "status": "pending",
                    },
                )
            return httpx.Response(
                200,
                json={"authority": "authority-123", "amount": 590_000, "status": "pending"},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            checkout = await KpayVerifier("https://kpay.website/api/v1", vault, client).create_transaction(
                shop_id="11111111-1111-4111-8111-111111111111",
                card_id="22222222-2222-4222-8222-222222222222",
                amount_rial=590_000,
                callback_url="https://bot.amupouya.org/payments/kpay/callback",
                order_id="order-123",
                description="Papilio plan",
            )
        self.assertEqual(checkout.payment_url, "https://kpay.website/pay/authority-123")
        self.assertEqual(
            requests,
            ["/api/v1/transactions/create", "/api/v1/transactions/payment/authority-123"],
        )

    async def test_missing_url_fails_if_public_record_amount_differs(self) -> None:
        vault = AsyncMock(spec=MysqlCredentialVault)
        vault.get.return_value = "test-token"

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return httpx.Response(
                    201,
                    json={
                        "id": "transaction-123", "authority": "authority-123",
                        "amount": 590_000, "status": "pending",
                    },
                )
            return httpx.Response(
                200,
                json={"authority": "authority-123", "amount": 590_010, "status": "pending"},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(PaymentProviderUnavailable):
                await KpayVerifier("https://kpay.website/api/v1", vault, client).create_transaction(
                    shop_id="11111111-1111-4111-8111-111111111111",
                    card_id="22222222-2222-4222-8222-222222222222",
                    amount_rial=590_000,
                    callback_url="https://bot.amupouya.org/payments/kpay/callback",
                    order_id="order-123",
                    description="Papilio plan",
                )

    async def test_checkout_rejects_wrong_amount_or_unsafe_url(self) -> None:
        vault = AsyncMock(spec=MysqlCredentialVault)
        vault.get.return_value = "test-token"
        for amount, url in (
            (590_001, "https://kpay.website/pay/authority"),
            (590_000, "https://fake-kpay.example/pay/authority"),
        ):
            def handler(
                _request: httpx.Request, response_amount: int = amount, response_url: str = url
            ) -> httpx.Response:
                return httpx.Response(
                    200,
                    json={
                        "id": "transaction-123",
                        "authority": "authority-123",
                        "amount": response_amount,
                        "status": "pending",
                        "payment_url": response_url,
                    },
                )

            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with self.assertRaises(PaymentProviderUnavailable):
                    await KpayVerifier("https://kpay.website/api/v1", vault, client).create_transaction(
                        shop_id="11111111-1111-4111-8111-111111111111",
                        card_id="22222222-2222-4222-8222-222222222222",
                        amount_rial=590_000,
                        callback_url="https://bot.amupouya.org/payments/kpay/callback",
                        order_id="order-123",
                        description="Papilio plan",
                    )

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
        service.verify_callback.return_value = CallbackOutcome.PAID
        app = create_app(service)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/payments/kpay/callback?authority=sample-authority")

        self.assertEqual(response.status_code, 200)
        self.assertIn("وضعیت تحویل سرویس را در بات", response.text)
        self.assertNotIn("لینک", response.text)
        service.verify_callback.assert_awaited_once_with("sample-authority")

    async def test_unconfigured_callback_fails_closed(self) -> None:
        app = create_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/payments/kpay/callback?authority=sample-authority")
        self.assertEqual(response.status_code, 503)
