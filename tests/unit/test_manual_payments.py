from __future__ import annotations

import io
import threading
from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from PIL import Image

from papilio_proxy.apps.api import create_app
from papilio_proxy.modules.accounts.admin.app.services import AdminWebService
from papilio_proxy.modules.accounts.admin.domain.entities import AdminSession
from papilio_proxy.modules.sales.payments.app.services import PaymentService
from papilio_proxy.modules.sales.payments.domain.entities import PaymentError
from papilio_proxy.modules.sales.payments.infra import images
from papilio_proxy.modules.sales.payments.interfaces import PaymentRepository
from tests.fixtures import receipt_image


class PaymentServiceTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.repository = AsyncMock(spec=PaymentRepository)
        self.service = PaymentService(self.repository)

    async def test_empty_methods_do_not_enable_sales(self) -> None:
        self.repository.methods.return_value = []
        self.assertFalse(await self.service.enabled(77))

    async def test_destination_is_dynamic_and_accepts_persian_digits(self) -> None:
        value = await self.service.save_method(
            method_id=None,
            title="کارت",
            card_number="۱۱۱۱ ۲۲۲۲ ۳۳۳۳ ۴۴۴۴",
            bank_name="بانک آزمایشی",
            account_holder="صاحب حساب",
            enabled=True,
        )
        self.assertEqual(value.card_number, "1111222233334444")
        self.repository.save_method.assert_awaited_once_with(value)

    async def test_invalid_destination_does_not_persist(self) -> None:
        for card, bank, holder in (
            ("123", "Bank", "Owner"),
            ("1111222233334444", " ", "Owner"),
            ("1111222233334444", "Bank", ""),
        ):
            with self.assertRaises(PaymentError):
                await self.service.save_method(
                    method_id=None,
                    title="Card",
                    card_number=card,
                    bank_name=bank,
                    account_holder=holder,
                    enabled=True,
                )
        self.repository.save_method.assert_not_awaited()

    async def test_approval_requires_bank_reference_and_normalizes_it(self) -> None:
        with self.assertRaises(PaymentError):
            await self.service.review("receipt", approved=True, actor="owner")
        self.repository.review.assert_not_awaited()
        await self.service.review("receipt", approved=True, actor="owner", bank_reference="۱۲۳-۴۵۶")
        self.repository.review.assert_awaited_once_with("receipt", True, "owner", "123456", "")

    async def test_rejection_requires_customer_reason(self) -> None:
        with self.assertRaises(PaymentError):
            await self.service.review("receipt", approved=False, actor="owner")
        await self.service.review(
            "receipt", approved=False, actor="owner", reason="  مبلغ صحیح نیست  "
        )
        self.repository.review.assert_awaited_once_with(
            "receipt", False, "owner", "", "مبلغ صحیح نیست"
        )


class ReceiptImageTests(IsolatedAsyncioTestCase):
    async def test_receipt_processing_runs_off_event_loop(self) -> None:
        loop_thread = threading.get_ident()
        workers: list[int] = []
        sanitize = images._sanitize

        def capture(value: bytes) -> bytes:
            workers.append(threading.get_ident())
            return sanitize(value)

        with patch.object(images, "_sanitize", capture):
            cleaned = await images.sanitize_receipt(receipt_image())
        self.assertNotEqual(workers, [loop_thread])
        with Image.open(io.BytesIO(cleaned)) as photo:
            self.assertEqual(photo.format, "JPEG")
            self.assertFalse(photo.getexif())

    async def test_nonimage_and_oversized_payload_are_rejected(self) -> None:
        for value in (b"", b"<svg/>", b"0" * (images.MAX_RECEIPT_BYTES + 1)):
            with self.assertRaises(PaymentError):
                await images.sanitize_receipt(value)


class PaymentAdminTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.repository = AsyncMock(spec=PaymentRepository)
        self.app = create_app()
        self.admin = AsyncMock(spec=AdminWebService)
        self.admin.session.return_value = AdminSession(
            "owner", "csrf", datetime.now(UTC) + timedelta(hours=1)
        )
        self.app.state.admin_web_service = self.admin
        self.app.state.admin_public_origin = "https://admin.example"
        self.app.state.payment_service = PaymentService(self.repository)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="https://admin.example"
        )
        self.client.cookies.set("papilio_admin_session", "session", path="/admin")
        self.headers = {"Origin": "https://admin.example", "X-CSRF-Token": "csrf"}
        self.receipt_id = str(uuid4())

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    async def test_receipt_image_is_private_no_store_and_read_does_not_approve(self) -> None:
        path = f"/admin/api/receipts/{self.receipt_id}/image"
        self.admin.session.return_value = None
        self.assertEqual((await self.client.get(path)).status_code, 401)
        self.repository.receipt_image.assert_not_awaited()
        self.admin.session.return_value = AdminSession(
            "owner", "csrf", datetime.now(UTC) + timedelta(hours=1)
        )
        self.repository.receipt_image.return_value = b"private-image"
        result = await self.client.get(path)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content, b"private-image")
        self.assertIn("no-store", result.headers["cache-control"])
        self.repository.review.assert_not_awaited()

    async def test_approval_requires_session_csrf_and_uses_authenticated_actor(self) -> None:
        path = f"/admin/api/receipts/{self.receipt_id}/decision"
        body = {"approved": True, "bank_reference": "123456"}
        self.admin.session.return_value = None
        self.assertEqual(
            (await self.client.post(path, json=body, headers=self.headers)).status_code, 401
        )
        self.admin.session.return_value = AdminSession(
            "owner", "csrf", datetime.now(UTC) + timedelta(hours=1)
        )
        self.assertEqual((await self.client.post(path, json=body)).status_code, 403)
        self.repository.review.assert_not_awaited()
        result = await self.client.post(path, json=body, headers=self.headers)
        self.assertEqual(result.status_code, 204)
        self.repository.review.assert_awaited_once_with(
            self.receipt_id, True, "owner", "123456", ""
        )

    async def test_methods_require_admin_and_store_explicit_destination(self) -> None:
        body = {
            "title": "کارت",
            "card_number": "1111222233334444",
            "bank_name": "Test bank",
            "account_holder": "Test owner",
            "enabled": True,
        }
        result = await self.client.post(
            "/admin/api/payment-methods", json=body, headers=self.headers
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["bank_name"], "Test bank")
        self.repository.save_method.assert_awaited_once()
        self.assertEqual(
            (await self.client.post("/admin/api/payment-methods", json=body)).status_code, 403
        )

    async def test_removed_gateway_routes_are_not_exposed(self) -> None:
        for path in ("/payments/kpay/callback", "/admin/api/checkout", "/receipt-checkout"):
            self.assertEqual((await self.client.get(path)).status_code, 404)
