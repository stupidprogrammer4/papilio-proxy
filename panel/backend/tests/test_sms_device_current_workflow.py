"""Actual enrolled-device revocation across a receiving-account lock wait."""

import asyncio
import hashlib
import hmac
import json
import time
from contextvars import Context
from datetime import UTC, datetime, timedelta

from papilio.infra.db.transaction import transaction
from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import text

from src.modules.billing.sms_devices.interfaces import ISmsSettlementCommand
from tests.test_checkout_financial_locks_workflow import wait_native_query
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowFixture,
)


class SmsDeviceCurrentWorkflowTest(StaffAdministrationWorkflowFixture):
    async def test_revoked_device_is_current_after_destination_lock_wait(self):
        destination = await self.post(
            "/v1/admin/payments/destinations",
            {
                "title": "Current receiving account",
                "kind": "card",
                "account": "6037990000000001",
                "recipient": "Owned recipient",
                "bank_name": "Owned bank",
                "is_active": True,
            },
        )
        device_data = {
            "label": "Current enrolled phone",
            "senders": ["OwnedBank"],
            "is_active": True,
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "approval_mode": "manual",
            "destination_id": destination["destination_id"],
        }
        enrollment = await self.post(
            "/v1/admin/payments/sms-devices", device_data
        )
        device = enrollment["device"]
        customer = await self.post(
            "/v1/admin/customers", {"display_name": "Current SMS payer"}
        )
        topup = await self.post(
            "/v1/admin/payments/topups",
            {
                "customer_id": customer["id"],
                "amount_rial": 120000,
                "destination_id": destination["destination_id"],
            },
        )
        event_id = "current_device_" + self.suffix
        raw = json.dumps(
            {
                "event_id": event_id,
                "sender": "OwnedBank",
                "message": "واریز ۱۲۰٬۰۰۰ ریال پیگیری ۱۲۳۴۵۶۷۸",
                "sent_at": datetime.now(UTC)
                .replace(microsecond=0)
                .isoformat(),
            }
        ).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(
            enrollment["api_key"].encode(),
            f"{device['id']}.{timestamp}.".encode() + raw,
            hashlib.sha256,
        ).hexdigest()
        uploaded = await self.client.post(
            f"/v1/webhooks/sms-devices/{device['id']}",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Papilio-Timestamp": timestamp,
                "X-Papilio-Signature": signature,
            },
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        automatic = await self.client.put(
            f"/v1/admin/payments/sms-devices/{device['id']}",
            headers=self.headers,
            json={
                **device_data,
                "approval_mode": "unique_sms",
                "expected_revision": device["revision"],
            },
        )
        self.assertEqual(automatic.status_code, 200, automatic.text)
        current = automatic.json()["data"]
        connections = {}
        started = asyncio.Event()

        async def settle():
            async with self.app.state.dishka_container() as scope:
                unit = await scope.get(MySQLUnitOfWork)
                command = await scope.get(ISmsSettlementCommand)
                async with transaction(unit):
                    connections["settle"] = (
                        await unit.execute(text("SELECT CONNECTION_ID()"))
                    ).scalar_one()
                    started.set()
                    result = await command.check_event(
                        event_id, expected_topup_id=topup["id"]
                    )
                return result

        task = None
        try:
            async with self.connection.uow() as holder:
                async with transaction(holder):
                    await holder.execute(
                        text(
                            "SELECT id FROM tbl_payment_destinations "
                            "WHERE id=:id FOR UPDATE"
                        ),
                        {"id": destination["destination_id"]},
                    )
                    task = asyncio.create_task(settle(), context=Context())
                    await asyncio.wait_for(started.wait(), 3)
                    await asyncio.to_thread(
                        wait_native_query,
                        self.raw["db"]["dsn"],
                        connections["settle"],
                        ("tbl_payment_destinations",),
                    )
                    revoke = asyncio.create_task(
                        self.client.put(
                            f"/v1/admin/payments/sms-devices/{device['id']}",
                            headers=self.headers,
                            json={
                                **device_data,
                                "approval_mode": "unique_sms",
                                "is_active": False,
                                "expected_revision": current["revision"],
                            },
                        ),
                        context=Context(),
                    )
                    revoked = await asyncio.wait_for(revoke, 5)
                    self.assertEqual(revoked.status_code, 200, revoked.text)
                    self.assertFalse(task.done())
            outcome = await asyncio.wait_for(task, 10)
        finally:
            if task is not None:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        # This proves the current device admission decision, independently of
        # the candidate reader's additional current-device eligibility filter.
        self.assertEqual(outcome, "manual")
        async with self.connection.uow() as fresh:
            result = (
                await fresh.execute(
                    text(
                        "SELECT t.status,t.approved_by_device_id,"
                        "t.approved_by_sms_id,"
                        "(SELECT COUNT(*) FROM tbl_wallet_entries e "
                        "WHERE e.reference=:reference) credits,"
                        "d.is_active,d.revision FROM tbl_topups t "
                        "JOIN tbl_sms_devices d ON d.id=:device "
                        "WHERE t.id=:topup"
                    ),
                    {
                        "reference": f"topup:{topup['id']}",
                        "device": device["id"],
                        "topup": topup["id"],
                    },
                )
            ).one()
        self.assertEqual(
            tuple(result),
            ("pending", None, None, 0, False, current["revision"] + 1),
        )
