from __future__ import annotations

import base64
import json
from typing import cast
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

import httpx

from bot.callback import create_app
from bot.infra.db.credentials import MysqlCredentialVault
from bot.infra.kpay import KpayVerifier
from bot.models.payments import PaymentProviderUnavailable, ProviderVerification
from bot.models.receipts import ReceiptOrder, ReceiptPaymentPage, ReceiptUnavailable
from bot.services.payments import PaymentSettlementError
from bot.services.receipts import ReceiptService

IMAGE = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\ntest").decode()


class ReceiptTests(IsolatedAsyncioTestCase):
    def service(self, paid: bool = False) -> ReceiptService:
        repository, provider, payments = (AsyncMock() for _ in range(3))
        repository.enabled.return_value = True
        repository.bound_order.return_value = ReceiptOrder("order", "auth", "tx", 50_000)
        repository.reserve.return_value = False
        provider.payment_page.return_value = ReceiptPaymentPage(
            50_000, 50_000, "1111222233334444", "Test", 120, "pending",
        )
        provider.verify.return_value = ProviderVerification(
            "auth", "paid" if paid else "pending", "tx", 50_000,
            "2026-10-02T00:00:00Z" if paid else None,
        )
        payments.settle_verified.return_value = True
        service = ReceiptService(repository, provider, payments)
        self.provider, self.repository, self.payments = provider, repository, payments
        return service

    async def test_pending_upload_never_calls_merchant_approval_or_settles(self) -> None:
        service = self.service()
        self.assertFalse(await service.submit("auth", IMAGE))
        self.provider.upload_receipt.assert_awaited_once_with("auth", IMAGE)
        self.repository.mark_uploaded.assert_awaited_once_with("order")
        self.provider.approve_receipt.assert_not_awaited()
        self.payments.settle_verified.assert_not_awaited()

    async def test_kpay_paid_upload_uses_existing_atomic_settlement(self) -> None:
        service = self.service(True)
        self.assertTrue(await service.submit("auth", IMAGE))
        self.payments.settle_verified.assert_awaited_once()
        self.provider.approve_receipt.assert_not_awaited()

    async def test_successful_upload_retry_does_not_upload_twice(self) -> None:
        service = self.service()
        self.repository.reserve.return_value = True
        self.assertFalse(await service.submit("auth", IMAGE))
        self.provider.upload_receipt.assert_not_awaited()

    async def test_background_recovers_provider_decision_without_receipt_reupload(self) -> None:
        service = self.service(True)
        self.repository.pending_uploads.return_value = ["auth"]
        self.assertEqual(await service.recheck_uploaded(), 1)
        self.provider.upload_receipt.assert_not_awaited()
        self.provider.approve_receipt.assert_not_awaited()

    async def test_disabled_unknown_expired_or_mismatched_order_cannot_upload(self) -> None:
        for mode in ("disabled", "unknown", "expired", "amount"):
            service = self.service()
            if mode == "disabled":
                self.repository.enabled.return_value = False
            elif mode == "unknown":
                self.repository.bound_order.return_value = None
            else:
                self.provider.payment_page.return_value = ReceiptPaymentPage(
                    60_000 if mode == "amount" else 50_000, 60_000,
                    "1111222233334444", "Test", 0 if mode == "expired" else 120, "pending",
                )
            with self.assertRaises(ReceiptUnavailable):
                await service.submit("auth", IMAGE)
            self.provider.upload_receipt.assert_not_awaited()

    async def test_wrong_provider_amount_never_settles(self) -> None:
        service = self.service(True)
        self.provider.verify.return_value = ProviderVerification(
            "auth", "paid", "tx", 60_000, "2026-10-02T00:00:00Z",
        )
        with self.assertRaises(PaymentSettlementError):
            await service.submit("auth", IMAGE)
        self.payments.settle_verified.assert_not_awaited()

    async def test_upload_failure_leaves_order_unsettled(self) -> None:
        service = self.service(True)
        self.provider.upload_receipt.side_effect = PaymentProviderUnavailable("Unavailable")
        with self.assertRaises(PaymentProviderUnavailable):
            await service.submit("auth", IMAGE)
        self.repository.mark_uploaded.assert_not_awaited()
        self.payments.settle_verified.assert_not_awaited()

    async def test_invalid_images_do_not_contact_provider(self) -> None:
        for image in ("text", "data:image/png;base64,@@@@", "data:image/png;base64,YWJj"):
            service = self.service()
            with self.assertRaises(ReceiptUnavailable):
                await service.submit("auth", image)
            self.provider.upload_receipt.assert_not_awaited()

    async def test_upload_adapter_preserves_actual_response_encrypted_without_approval(self) -> None:
        vault = AsyncMock(spec=MysqlCredentialVault)
        payload = {"status": "pending", "message": "Receipt accepted", "details": {"example": True}}
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            self.assertEqual(json.loads(request.content), {"receipt_image": IMAGE})
            return httpx.Response(200, json=payload)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await KpayVerifier("https://example.test", vault, client).upload_receipt("auth", IMAGE)
        self.assertEqual(seen, ["/transactions/payment/auth/upload-receipt"])
        self.assertEqual(json.loads(vault.put.await_args.args[1]), {"http_status": 200, "body": payload})
        self.assertNotIn("auth", vault.put.await_args.args[0])

    async def test_browser_page_origin_body_limit_xss_and_return_route(self) -> None:
        service = AsyncMock(spec=ReceiptService)
        service.page.return_value = ReceiptPaymentPage(
            50_000, 50_000, "1111222233334444", "<script>bad</script>", 120, "pending",
        )
        service.submit.return_value = True
        app = create_app(AsyncMock())
        app.state.receipt_service = service
        app.state.admin_public_origin = "https://testserver"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
            page = await client.get("/payments/kpay/checkout/auth")
            self.assertEqual(page.status_code, 200)
            self.assertIn("5,000", page.text)
            self.assertNotIn("<script>bad</script>", page.text)
            self.assertIn("no-store", page.headers["cache-control"])
            denied = await client.post("/payments/kpay/checkout/auth/receipt", json={"image": IMAGE})
            self.assertEqual(denied.status_code, 403)
            oversized = await client.post("/payments/kpay/checkout/auth/receipt", content=b"x"*2_702_000,
                                          headers={"Origin": "https://testserver"})
            self.assertEqual(oversized.status_code, 413)
            good = await client.post("/payments/kpay/checkout/auth/receipt", json={"image": IMAGE},
                                     headers={"Origin": "https://testserver"})
            self.assertEqual(good.status_code, 200)
            self.assertEqual(good.json(), {"paid": True, "callback": "/payments/kpay/callback?authority=auth"})
        cast(AsyncMock, service.submit).assert_awaited_once_with("auth", IMAGE)
