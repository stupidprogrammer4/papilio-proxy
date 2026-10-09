import asyncio
import hashlib
import hmac
import json
import threading
import time
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import text

from tests.test_customer_checkout_workflow import CustomerCheckoutWorkflowTest
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowTest,
)
from tests.test_support_workflow import SupportWorkflowTest
from tests.test_usage_workflow import UsageWorkflowTest


class EventLoopWorkflowTest(SupportWorkflowTest):
    async def test_signed_sms_responsiveness_and_committed_observation(self):
        body = json.dumps(
            {
                "event_id": "cpu_" + uuid4().hex,
                "sender": "bank-fixture",
                "message": "واریز 100000 ریال پیگیری 12345678",
                "sent_at": datetime.now(UTC).isoformat(),
            }
        ).encode()
        timestamp = str(int(time.time()))
        original = hmac.new
        signature = original(
            self.settings.security.sms_webhook_key.encode(),
            timestamp.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        entered, completed = threading.Event(), threading.Event()

        def delayed(*args, **kwargs):
            entered.set()
            time.sleep(0.15)
            result = original(*args, **kwargs)
            completed.set()
            return result

        async def heartbeat():
            started = await asyncio.to_thread(entered.wait, 2)
            self.assertTrue(started)
            self.assertFalse(
                completed.is_set(),
                "Signature computation blocked the event loop",
            )

        with patch(
            "src.modules.billing.sms.routers.webhook.hmac.new", new=delayed
        ):
            response, heartbeat_result = await asyncio.gather(
                self.client.post(
                    "/v1/webhooks/sms",
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Papilio-Timestamp": timestamp,
                        "X-Papilio-Signature": signature,
                    },
                ),
                heartbeat(),
                return_exceptions=True,
            )
        if isinstance(heartbeat_result, BaseException):
            raise heartbeat_result
        if isinstance(response, BaseException):
            raise response
        self.assertEqual(response.status_code, 200)
        async with self.connection.uow() as unit:
            found = (
                await unit.execute(
                    text(
                        "SELECT amount_rial,bank_reference "
                        "FROM tbl_sms_events WHERE event_id=:id"
                    ),
                    {"id": json.loads(body)["event_id"]},
                )
            ).one()
            self.assertEqual(tuple(found), (100000, "12345678"))

    async def test_customer_link_hash_responsive_and_one_use_unchanged(self):
        from src.modules.accounts.customer_auth.app import commands

        original = commands.hash_sha256
        entered, completed = threading.Event(), threading.Event()

        def delayed(value):
            entered.set()
            time.sleep(0.15)
            result = original(value)
            completed.set()
            return result

        async def heartbeat():
            started = await asyncio.to_thread(entered.wait, 2)
            self.assertTrue(started)
            self.assertFalse(
                completed.is_set(), "Token hashing blocked the event loop"
            )

        identity = {
            "telegram_id": int(uuid4().hex[:12], 16),
            "display_name": "ورود آزمون پردازش",
        }
        with patch.object(commands, "hash_sha256", new=delayed):
            response, heartbeat_result = await asyncio.gather(
                self.client.post(
                    "/v1/bot/account-link",
                    headers={
                        "X-Papilio-Bot-Key": (
                            self.settings.security.bot_service_key
                        )
                    },
                    json=identity,
                ),
                heartbeat(),
                return_exceptions=True,
            )
        if isinstance(heartbeat_result, BaseException):
            raise heartbeat_result
        if isinstance(response, BaseException):
            raise response
        self.assertEqual(response.status_code, 200)
        token = response.json()["data"]["url"].split("#", 1)[1]
        exchanged = await self.client.post(
            "/v1/customer/auth/exchange",
            headers={"Origin": self.settings.public.customer_portal_origin},
            json={"token": token},
        )
        self.assertEqual(exchanged.status_code, 200)
        replay = await self.client.post(
            "/v1/customer/auth/exchange",
            headers={"Origin": self.settings.public.customer_portal_origin},
            json={"token": token},
        )
        self.assertEqual(replay.status_code, 401)

    async def test_receipt_crypto_responsive_cancellation_and_recovery(self):
        from io import BytesIO

        from PIL import Image

        from src.modules.billing.receipts.app import commands

        def image_content():
            output = BytesIO()
            Image.new("RGB", (32, 32), (10, 30, 80)).save(
                output, format="JPEG"
            )
            return output.getvalue()

        content = await asyncio.to_thread(image_content)
        client, headers, customer_id = await self.account()
        topup = await self.post(
            "/v1/admin/payments/topups",
            {"customer_id": customer_id, "amount_rial": 100000},
        )
        original = commands.encrypt
        entered, completed = threading.Event(), threading.Event()

        def delayed(plaintext, key):
            entered.set()
            time.sleep(0.15)
            result = original(plaintext, key)
            completed.set()
            return result

        async def heartbeat():
            started = await asyncio.to_thread(entered.wait, 2)
            self.assertTrue(started)
            self.assertFalse(
                completed.is_set(), "Receipt encryption blocked the event loop"
            )

        path = f"/v1/customer/topups/{topup['id']}/receipts"
        try:
            with patch.object(commands, "encrypt", new=delayed):
                request = asyncio.create_task(
                    client.post(
                        path,
                        headers=headers,
                        files={"file": ("receipt.jpg", content, "image/jpeg")},
                    )
                )
                await heartbeat()
                request.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await request
                self.assertTrue(await asyncio.to_thread(completed.wait, 2))
            async with self.connection.uow() as unit:
                count = (
                    await unit.execute(
                        text(
                            "SELECT COUNT(*) FROM tbl_payment_receipts "
                            "WHERE topup_id=:id"
                        ),
                        {"id": topup["id"]},
                    )
                ).scalar_one()
                self.assertEqual(count, 0)
            entered.clear()
            completed.clear()
            with patch.object(commands, "encrypt", new=delayed):
                response, heartbeat_result = await asyncio.gather(
                    client.post(
                        path,
                        headers=headers,
                        files={"file": ("receipt.jpg", content, "image/jpeg")},
                    ),
                    heartbeat(),
                    return_exceptions=True,
                )
            if isinstance(heartbeat_result, BaseException):
                raise heartbeat_result
            if isinstance(response, BaseException):
                raise response
            self.assertEqual(response.status_code, 200)
            receipt = response.json()["data"]
            duplicate = await client.post(
                path,
                headers=headers,
                files={"file": ("receipt.jpg", content, "image/jpeg")},
            )
            self.assertEqual(duplicate.json()["data"]["id"], receipt["id"])
            download = await client.get(f"{path}/{receipt['id']}")
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.headers["content-type"], "image/jpeg")
            digest = hashlib.sha256(download.content).hexdigest()
            async with self.connection.uow() as unit:
                stored = (
                    await unit.execute(
                        text(
                            "SELECT content_hash,encrypted_payload "
                            "FROM tbl_payment_receipts WHERE id=:id"
                        ),
                        {"id": receipt["id"]},
                    )
                ).one()
                self.assertEqual(stored.content_hash, digest)
                self.assertNotIn(
                    content.decode("latin1"), stored.encrypted_payload
                )
        finally:
            await client.aclose()


class EventLoopCheckoutWorkflowTest(
    CustomerCheckoutWorkflowTest, StaffAdministrationWorkflowTest
):
    pass


class EventLoopUsageWorkflowTest(
    UsageWorkflowTest, StaffAdministrationWorkflowTest
):
    pass
