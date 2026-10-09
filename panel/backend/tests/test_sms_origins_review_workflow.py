"""Current operator capabilities must not advertise an expired source."""

import asyncio
from datetime import UTC, timedelta

from sqlalchemy import text

from tests.test_sms_origins_workflow import (
    DeviceExpiryObservation,
    SmsOriginsWorkflowFixture,
    wait_owned_device_expired,
)


class SmsOriginsReviewWorkflowTest(SmsOriginsWorkflowFixture):
    async def test_current_review_disallows_expired_enrolled_source(self):
        source = await self.receiving_source()
        event = "review_source_expiry_" + self.suffix
        await self.upload_origin(
            source["enrolled"], self.original_timestamp(source), event
        )
        sms_id = await self.observed_id(event)
        async with self.connection.uow() as fresh:
            clock = await fresh.execute(text("SELECT UTC_TIMESTAMP(6)"))
            expiry = clock.scalar_one().replace(tzinfo=UTC) + timedelta(
                seconds=4
            )
        device_id = source["enrolled"]["device"]["id"]
        response = await self.client.put(
            f"/v1/admin/payments/sms-devices/{device_id}",
            headers=self.headers,
            json={
                **source["device_body"],
                "expires_at": expiry.isoformat(),
                "expected_revision": source["enrolled"]["device"]["revision"],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        await asyncio.to_thread(
            wait_owned_device_expired,
            DeviceExpiryObservation(
                dsn=self.raw["db"]["dsn"], device_id=device_id
            ),
        )
        review = (
            await self.get(
                f"/v1/admin/payments/sms-origins/sms-events/{sms_id}/review"
            )
        )["data"]
        async with self.connection.uow() as fresh:
            counts = await fresh.execute(
                text(
                    "SELECT (SELECT COALESCE(SUM(balance_rial),0) FROM "
                    "tbl_wallets) AS balance, (SELECT COUNT(*) FROM "
                    "tbl_wallet_entries) AS entries, (SELECT COUNT(*) FROM "
                    "tbl_sms_settlements) AS settlements"
                )
            )
            state = counts.mappings().one()
        self.assertEqual(
            (state["balance"], state["entries"], state["settlements"]),
            (0, 0, 0),
        )
        self.assertFalse(
            review["manual_approval_available"],
            "A fresh operator response advertised approval from an expired "
            "enrolled phone",
        )
