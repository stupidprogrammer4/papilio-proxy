import asyncio
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowTest,
)


class SmsDevicesWorkflowTest(StaffAdministrationWorkflowTest):
    async def settlement_check(self, topup_id):
        from src.modules.billing.sms_devices.interfaces import (
            ISmsSettlementCommand,
        )

        async with self.app.state.dishka_container() as scope:
            command = await scope.get(ISmsSettlementCommand)
            result = await command.check_topup(topup_id)
            return result

    async def test_destination_wide_ambiguity_and_disabled_destination(self):
        destination, original = await self.automatic_device()
        original_data = {
            **self.device_data(),
            "destination_id": destination["destination_id"],
            "approval_mode": "manual",
            "expected_revision": original["device"]["revision"],
        }
        changed = await self.client.put(
            f"/v1/admin/payments/sms-devices/{original['device']['id']}",
            headers=self.headers,
            json=original_data,
        )
        self.assertEqual(changed.status_code, 200)
        second = await self.post(
            "/v1/admin/payments/sms-devices",
            {**original_data, "label": "Second enrolled source"},
        )
        _, topup = await self.topup(destination["destination_id"], "multi")
        first_upload = await self.upload(
            original["device"]["id"], original["api_key"]
        )
        second_upload = await self.upload(
            second["device"]["id"],
            second["api_key"],
            event="second_" + self.suffix,
            message="واریز ۱۲۰۰۰۰ ریال پیگیری ۸۷۶۵۴۳۲۱",
        )
        self.assertEqual(first_upload.status_code, 200)
        self.assertEqual(second_upload.status_code, 200)
        activated_original = await self.client.put(
            f"/v1/admin/payments/sms-devices/{original['device']['id']}",
            headers=self.headers,
            json={
                **original_data,
                "approval_mode": "unique_sms",
                "expected_revision": changed.json()["data"]["revision"],
            },
        )
        activated_second = await self.client.put(
            f"/v1/admin/payments/sms-devices/{second['device']['id']}",
            headers=self.headers,
            json={
                **original_data,
                "approval_mode": "unique_sms",
                "expected_revision": second["device"]["revision"],
            },
        )
        self.assertEqual(activated_original.status_code, 200)
        self.assertEqual(activated_second.status_code, 200)
        self.assertEqual(await self.settlement_check(topup["id"]), "ambiguous")
        disabled = await self.client.put(
            f"/v1/admin/payments/destinations/{destination['destination_id']}",
            headers=self.headers,
            json={
                "title": destination["title"],
                "kind": "card",
                "account": destination["account"],
                "recipient": destination["recipient"],
                "bank_name": destination["bank_name"],
                "is_active": False,
            },
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertEqual(await self.settlement_check(topup["id"]), "manual")
        async with self.connection.uow() as fresh:
            status = (
                await fresh.execute(
                    text("SELECT status FROM tbl_topups WHERE id=:id"),
                    {"id": topup["id"]},
                )
            ).scalar_one()
            credits = (
                await fresh.execute(
                    text("SELECT count(*) FROM tbl_wallet_entries")
                )
            ).scalar_one()
        self.assertEqual(status, "pending")
        self.assertEqual(credits, 0)

    def device_data(self):
        return {
            "label": "Owned bank phone",
            "senders": ["OwnedBank"],
            "is_active": True,
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        }

    async def upload(
        self,
        device,
        key,
        *,
        event=None,
        sender="OwnedBank",
        timestamp=None,
        message="واریز ۱۲۰٬۰۰۰ ریال پیگیری ۱۲۳۴۵۶۷۸",
        sent_at=None,
    ):
        payload = {
            "event_id": event or "phone_" + self.suffix,
            "sender": sender,
            "message": message,
            "sent_at": sent_at
            or datetime.now(UTC).replace(microsecond=0).isoformat(),
        }
        raw = json.dumps(payload).encode()
        timestamp = timestamp or str(int(time.time()))
        signature = hmac.new(
            key.encode(),
            f"{device}.{timestamp}.".encode() + raw,
            hashlib.sha256,
        ).hexdigest()
        result = await self.client.post(
            f"/v1/webhooks/sms-devices/{device}",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Papilio-Timestamp": timestamp,
                "X-Papilio-Signature": signature,
            },
        )
        return result

    async def test_native_enrollment_provenance_rotation_and_revocation(self):
        data = self.device_data()
        enrollment = await self.post("/v1/admin/payments/sms-devices", data)
        device, key = enrollment["device"], enrollment["api_key"]
        page = await self.get("/v1/admin/payments/sms-devices")
        self.assertNotIn(key, json.dumps(page))
        self.assertNotIn("encrypted_key", json.dumps(page))
        filtered = await self.get(
            "/v1/admin/payments/sms-devices?q=%25&per_page=1"
        )
        self.assertEqual(filtered["meta"]["pager"]["total_items"], 0)
        matching = await self.get(
            "/v1/admin/payments/sms-devices?q=Owned%20bank&per_page=1"
        )
        self.assertEqual(matching["data"][0]["id"], device["id"])
        uploaded = await self.upload(device["id"], key)
        self.assertEqual(uploaded.status_code, 200)
        rotated = await self.post(
            f"/v1/admin/payments/sms-devices/{device['id']}/rotate",
            {"expected_revision": device["revision"]},
        )
        denied = await self.upload(
            device["id"], key, event="revoked_" + self.suffix
        )
        self.assertEqual(denied.status_code, 401)
        accepted = await self.upload(
            device["id"], rotated["api_key"], event="rotated_" + self.suffix
        )
        self.assertEqual(accepted.status_code, 200)
        assert self.settings.sms_devices is not None
        self.settings.sms_devices.enabled = False
        blocked_enrollment = await self.client.post(
            "/v1/admin/payments/sms-devices",
            headers=self.headers,
            json={**data, "is_active": False},
        )
        self.assertEqual(blocked_enrollment.status_code, 409)
        disabled = await self.client.put(
            f"/v1/admin/payments/sms-devices/{device['id']}",
            headers=self.headers,
            json={
                **data,
                "is_active": False,
                "expected_revision": rotated["device"]["revision"],
            },
        )
        self.assertEqual(disabled.status_code, 200)
        self.settings.sms_devices.enabled = True
        denied = await self.upload(
            device["id"], rotated["api_key"], event="disabled_" + self.suffix
        )
        self.assertEqual(denied.status_code, 401)
        async with self.connection.uow() as fresh:
            rows = (
                await fresh.execute(
                    text(
                        "SELECT device_id,amount_rial,bank_reference FROM "
                        "tbl_sms_events ORDER BY id"
                    )
                )
            ).all()
            ciphertext = (
                await fresh.execute(
                    text(
                        "SELECT encrypted_key FROM tbl_sms_devices "
                        "WHERE id=:id"
                    ),
                    {"id": device["id"]},
                )
            ).scalar_one()
        self.assertEqual(len(rows), 2)
        self.assertTrue(
            all(
                row.device_id == device["id"]
                and row.amount_rial == 120000
                and row.bank_reference == "12345678"
                for row in rows
            )
        )
        self.assertNotIn(rotated["api_key"], ciphertext)

    async def test_native_sender_signature_clock_expiry_and_scopes(self):
        data = self.device_data()
        enrollment = await self.post("/v1/admin/payments/sms-devices", data)
        device, key = enrollment["device"], enrollment["api_key"]
        denied_sender = await self.upload(
            device["id"], key, sender="UnenrolledBank"
        )
        self.assertEqual(denied_sender.status_code, 403)
        denied_key = await self.upload(device["id"], "wrong-key")
        self.assertEqual(denied_key.status_code, 401)
        expired_clock = await self.upload(device["id"], key, timestamp="1")
        self.assertEqual(expired_clock.status_code, 401)
        stale = await self.client.put(
            f"/v1/admin/payments/sms-devices/{device['id']}",
            headers=self.headers,
            json={**data, "expected_revision": device["revision"] + 1},
        )
        self.assertEqual(stale.status_code, 409)
        staff = await self.post(
            "/v1/admin/staff",
            {
                "username": "phone_reader_" + self.suffix,
                "password": "phone-test-password",
                "is_active": True,
                "scopes": ["payments:read"],
            },
        )
        reader, headers = await self.login_staff(
            staff["username"], "phone-test-password"
        )
        try:
            page = await reader.get("/v1/admin/payments/sms-devices")
            self.assertEqual(page.status_code, 200)
            denied = await reader.post(
                f"/v1/admin/payments/sms-devices/{device['id']}/rotate",
                headers=headers,
                json={"expected_revision": device["revision"]},
            )
            self.assertEqual(denied.status_code, 403)
        finally:
            await reader.aclose()
        updater = await self.post(
            "/v1/admin/staff",
            {
                "username": "phone_updater_" + self.suffix,
                "password": "phone-test-password",
                "is_active": True,
                "scopes": ["payments:update"],
            },
        )
        writer, writer_headers = await self.login_staff(
            updater["username"], "phone-test-password"
        )
        try:
            rotated = await writer.post(
                f"/v1/admin/payments/sms-devices/{device['id']}/rotate",
                headers=writer_headers,
                json={"expected_revision": device["revision"]},
            )
            self.assertEqual(rotated.status_code, 200)
            forbidden = await writer.post(
                "/v1/admin/payments/sms-devices",
                headers=writer_headers,
                json=data,
            )
            self.assertEqual(forbidden.status_code, 403)
        finally:
            await writer.aclose()
        async with self.connection.uow() as fresh:
            await fresh.execute(
                text(
                    "UPDATE tbl_sms_devices SET expires_at=:expiry WHERE "
                    "id=:id"
                ),
                {
                    "id": device["id"],
                    "expiry": datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(seconds=1),
                },
            )
            await fresh.commit()
        expired_key = await self.upload(device["id"], key)
        self.assertEqual(expired_key.status_code, 401)

    async def automatic_device(self):
        destination = await self.post(
            "/v1/admin/payments/destinations",
            {
                "title": "Owned bank destination",
                "kind": "card",
                "account": "6037990000000001",
                "recipient": "Owned recipient",
                "bank_name": "Owned bank",
                "is_active": True,
            },
        )
        device = await self.post(
            "/v1/admin/payments/sms-devices",
            {
                **self.device_data(),
                "approval_mode": "unique_sms",
                "destination_id": destination["destination_id"],
            },
        )
        return destination, device

    async def topup(self, destination_id, suffix):
        customer = await self.post(
            "/v1/admin/customers", {"display_name": "Owned payer " + suffix}
        )
        topup = await self.post(
            "/v1/admin/payments/topups",
            {
                "customer_id": customer["id"],
                "amount_rial": 120000,
                "destination_id": destination_id,
            },
        )
        return customer, topup

    async def test_native_unique_sms_settlement_replay_and_notification(self):
        destination, enrollment = await self.automatic_device()
        customer, topup = await self.topup(
            destination["destination_id"], "unique"
        )
        sent_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        accepted = await self.upload(
            enrollment["device"]["id"], enrollment["api_key"], sent_at=sent_at
        )
        self.assertEqual(accepted.status_code, 200)
        replay = await self.upload(
            enrollment["device"]["id"], enrollment["api_key"], sent_at=sent_at
        )
        self.assertEqual(replay.status_code, 200)
        async with self.connection.uow() as fresh:
            approved = (
                await fresh.execute(
                    text(
                        "SELECT "
                        "status,approved_by_device_id,approved_by_sms_id,approved_by_staff_id"
                        " FROM tbl_topups WHERE id=:id"
                    ),
                    {"id": topup["id"]},
                )
            ).one()
            balance = (
                await fresh.execute(
                    text(
                        "SELECT balance_rial FROM tbl_wallets WHERE "
                        "customer_id=:id"
                    ),
                    {"id": customer["id"]},
                )
            ).scalar_one()
            credits = (
                await fresh.execute(
                    text(
                        "SELECT count(*) FROM tbl_wallet_entries WHERE "
                        "reference=:reference"
                    ),
                    {"reference": f"topup:{topup['id']}"},
                )
            ).scalar_one()
            notices = (
                await fresh.execute(
                    text(
                        "SELECT count(*) FROM tbl_notifications WHERE "
                        "customer_id=:id AND kind='payment_approved'"
                    ),
                    {"id": customer["id"]},
                )
            ).scalar_one()
        self.assertEqual(approved.status, "approved")
        self.assertEqual(
            approved.approved_by_device_id, enrollment["device"]["id"]
        )
        self.assertIsNotNone(approved.approved_by_sms_id)
        self.assertIsNone(approved.approved_by_staff_id)
        self.assertEqual(balance, 120000)
        self.assertEqual(credits, 1)
        self.assertEqual(notices, 1)
        public_payment = (
            await self.get(f"/v1/admin/payments/topups/{topup['id']}")
        )["data"]
        self.assertEqual(
            public_payment["approved_by_device_id"],
            enrollment["device"]["id"],
        )
        self.assertEqual(
            public_payment["approved_by_sms_id"], approved.approved_by_sms_id
        )
        public_sms = (await self.get("/v1/admin/payments/sms"))["data"]
        self.assertTrue(
            all(
                row["device_id"] == enrollment["device"]["id"]
                and "message" not in row
                and "encrypted_key" not in row
                for row in public_sms
            )
        )

    async def test_manual_and_sms_approval_race_credits_topup_once(self):
        destination, enrollment = await self.automatic_device()
        customer, topup = await self.topup(
            destination["destination_id"], "manual_sms_race"
        )
        bank_reference = "race_" + self.suffix[:12]
        sent_at = datetime.now(UTC).replace(microsecond=0).isoformat()

        manual, sms = await asyncio.gather(
            self.client.post(
                f"/v1/admin/payments/topups/{topup['id']}/approve",
                headers=self.headers,
                json={
                    "expected_revision": 1,
                    "bank_reference": bank_reference,
                },
            ),
            self.upload(
                enrollment["device"]["id"],
                enrollment["api_key"],
                event="race_" + self.suffix,
                message=f"واریز ۱۲۰٬۰۰۰ ریال پیگیری {bank_reference}",
                sent_at=sent_at,
            ),
        )

        self.assertEqual(manual.status_code, 200, manual.text)
        self.assertEqual(sms.status_code, 200, sms.text)
        async with self.connection.uow() as fresh:
            topup_state = (
                await fresh.execute(
                    text(
                        "SELECT status,bank_reference FROM tbl_topups "
                        "WHERE id=:id"
                    ),
                    {"id": topup["id"]},
                )
            ).one()
            wallet_balance = (
                await fresh.execute(
                    text(
                        "SELECT balance_rial FROM tbl_wallets "
                        "WHERE customer_id=:id"
                    ),
                    {"id": customer["id"]},
                )
            ).scalar_one()
            credit_count = (
                await fresh.execute(
                    text(
                        "SELECT COUNT(*) FROM tbl_wallet_entries "
                        "WHERE reference=:reference"
                    ),
                    {"reference": f"topup:{topup['id']}"},
                )
            ).scalar_one()

        self.assertEqual(topup_state.status, "approved")
        self.assertEqual(topup_state.bank_reference, bank_reference)
        self.assertEqual(wallet_balance, 120000)
        self.assertEqual(credit_count, 1)

    async def test_manual_bank_reference_blocks_sms_credit_to_another_topup(
        self,
    ):
        destination, enrollment = await self.automatic_device()
        first_customer, manually_paid = await self.topup(
            destination["destination_id"], "manual_reference_owner"
        )
        second_customer, sms_candidate = await self.topup(
            destination["destination_id"], "sms_reference_candidate"
        )
        bank_reference = "reuse_" + self.suffix[:12]
        manual = await self.post(
            f"/v1/admin/payments/topups/{manually_paid['id']}/approve",
            {"expected_revision": 1, "bank_reference": bank_reference},
        )
        self.assertEqual(manual["status"], "approved")

        accepted = await self.upload(
            enrollment["device"]["id"],
            enrollment["api_key"],
            event="reuse_" + self.suffix,
            message=f"واریز ۱۲۰٬۰۰۰ ریال پیگیری {bank_reference}",
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(
            await self.settlement_check(sms_candidate["id"]), "waiting"
        )

        first = await self.get(
            f"/v1/admin/payments/topups/{manually_paid['id']}"
        )
        second = await self.get(
            f"/v1/admin/payments/topups/{sms_candidate['id']}"
        )
        self.assertEqual(first["data"]["status"], "approved")
        self.assertEqual(first["data"]["bank_reference"], bank_reference)
        self.assertEqual(second["data"]["status"], "pending")
        first_wallet = await self.get(
            f"/v1/admin/payments/wallets/{first_customer['id']}"
        )
        second_wallet = await self.get(
            f"/v1/admin/payments/wallets/{second_customer['id']}"
        )
        self.assertEqual(first_wallet["data"]["balance_rial"], 120000)
        self.assertEqual(second_wallet["data"]["balance_rial"], 0)

    async def test_native_ambiguous_amount_and_uncertain_sms_remain_unapproved(
        self,
    ):
        destination, enrollment = await self.automatic_device()
        _, first = await self.topup(destination["destination_id"], "first")
        _, second = await self.topup(destination["destination_id"], "second")
        accepted = await self.upload(
            enrollment["device"]["id"], enrollment["api_key"]
        )
        self.assertEqual(accepted.status_code, 200)
        review = await self.post(
            f"/v1/admin/payments/reviews/{first['id']}/check"
        )
        self.assertEqual(review["status"], "ambiguous")
        async with self.connection.uow() as fresh:
            states = (
                (
                    await fresh.execute(
                        text("SELECT status FROM tbl_topups ORDER BY id")
                    )
                )
                .scalars()
                .all()
            )
            credits = (
                await fresh.execute(
                    text("SELECT count(*) FROM tbl_wallet_entries")
                )
            ).scalar_one()
        self.assertEqual(states, ["pending", "pending"])
        self.assertEqual(credits, 0)
        await self.post(
            f"/v1/admin/payments/topups/{first['id']}/approve",
            {"expected_revision": 1, "bank_reference": "12345678"},
        )
        debit = await self.upload(
            enrollment["device"]["id"],
            enrollment["api_key"],
            event="debit_" + self.suffix,
            message="برداشت ۱۲۰۰۰۰ ریال پیگیری ۵۵۵۵۵۵",
        )
        self.assertEqual(debit.status_code, 200)
        uncertain = await self.upload(
            enrollment["device"]["id"],
            enrollment["api_key"],
            event="uncertain_" + self.suffix,
            message="واریز ۱۲۰۰۰۰ ریال مانده ۹۹۹۰۰۰ ریال پیگیری ۶۶۶۶۶۶",
        )
        self.assertEqual(uncertain.status_code, 200)
        async with self.connection.uow() as fresh:
            pending = (
                await fresh.execute(
                    text("SELECT status FROM tbl_topups WHERE id=:id"),
                    {"id": second["id"]},
                )
            ).scalar_one()
            malformed = (
                await fresh.execute(
                    text(
                        "SELECT count(*) FROM tbl_sms_events "
                        "WHERE amount_rial IS NULL"
                    )
                )
            ).scalar_one()
        self.assertEqual(pending, "pending")
        self.assertEqual(malformed, 2)
