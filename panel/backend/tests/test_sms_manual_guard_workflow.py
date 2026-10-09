"""Current non-automatic SMS sources retain their manual decision category."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from src.modules.billing.sms_devices.interfaces import ISmsSettlementCommand
from tests.test_checkout_workflow import CheckoutWorkflowTest


class SmsManualGuardWorkflowTest(CheckoutWorkflowTest):
    async def settle(self, event_id):
        async with self.app.state.dishka_container() as scope:
            command = await scope.get(ISmsSettlementCommand)
            result = await command.check_event(event_id)
        return result

    async def test_manual_source_precedes_hint_and_timestamp_results(self):
        destination = await self.post(
            "/v1/admin/payments/destinations",
            {
                "title": "Manual source receiving account",
                "kind": "card",
                "account": "6037990000000001",
                "recipient": "Owned recipient",
                "bank_name": "Owned bank",
                "is_active": True,
            },
        )
        enrollment = await self.post(
            "/v1/admin/payments/sms-devices",
            {
                "label": "Manual enrolled phone",
                "senders": ["OwnedBank"],
                "is_active": True,
                "expires_at": (
                    datetime.now(UTC) + timedelta(days=30)
                ).isoformat(),
                "approval_mode": "manual",
                "destination_id": destination["destination_id"],
            },
        )
        device_id = enrollment["device"]["id"]
        event = "manual_guard_" + self.suffix
        received = await self.upload_checkout_sms(
            device_id, enrollment["api_key"], event=event
        )
        self.assertEqual(received.status_code, 200, received.text)
        with self.subTest(case="zero_matching_topups"):
            self.assertEqual(await self.settle(event), "manual")
        customer = await self.post(
            "/v1/admin/customers", {"display_name": "Manual source payer"}
        )
        first = await self.post(
            "/v1/admin/payments/topups",
            {
                "customer_id": customer["id"],
                "amount_rial": 120000,
                "destination_id": destination["destination_id"],
            },
        )
        second = await self.post(
            "/v1/admin/payments/topups",
            {
                "customer_id": customer["id"],
                "amount_rial": 120000,
                "destination_id": destination["destination_id"],
            },
        )
        with self.subTest(case="multiple_matching_topups"):
            self.assertEqual(await self.settle(event), "manual")
        old_event = "outside_guard_" + self.suffix
        received = await self.upload_checkout_sms(
            device_id,
            enrollment["api_key"],
            event=old_event,
            sent_at=(
                datetime.now(UTC)
                - timedelta(
                    hours=self.settings.operations.sms_match_window_hours + 1
                )
            ).isoformat(),
        )
        self.assertEqual(received.status_code, 200, received.text)
        with self.subTest(case="outside_matching_window"):
            self.assertEqual(await self.settle(old_event), "manual")
        async with self.connection.uow() as unit:
            state = (
                await unit.execute(
                    text(
                        "SELECT "
                        "(SELECT COUNT(*) FROM tbl_topups t "
                        "WHERE t.id IN (:first,:second) "
                        "AND t.status='pending') pending,"
                        "(SELECT COUNT(*) FROM tbl_wallet_entries e "
                        "JOIN tbl_wallets w ON w.id=e.wallet_id "
                        "WHERE w.customer_id=:customer) ledger_entries,"
                        "(SELECT COUNT(*) FROM tbl_subscriptions s "
                        "WHERE s.customer_id=:customer) subscriptions"
                    ),
                    {
                        "first": first["id"],
                        "second": second["id"],
                        "customer": customer["id"],
                    },
                )
            ).one()
        self.assertEqual(tuple(state), (2, 0, 0))
