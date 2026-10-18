import asyncio
import json
import os
from contextvars import Context
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from papilio.infra.db.transaction import transaction
from sqlalchemy import text, update
from sqlalchemy.engine import make_url

from src.modules.operations.preferences.infra.tables import (
    PreferencesRevisionTable,
)
from tests.test_fulfillment_workflow import (
    FulfillmentWorkflowFixture,
)
from tests.test_fulfillment_workflow import (
    FulfillmentWorkflowTest as Paid,
)
from tests.test_support_workflow import SupportWorkflowTest


class TrialsWorkflowTest(SupportWorkflowTest, Paid):
    async def source(self):
        plan = await self.post(
            "/v1/admin/plans",
            {
                "code": "trial_" + uuid4().hex,
                "title": "منبع آزمایشی",
                "quota_bytes": 1000000000,
                "duration_days": 30,
                "price_rial": 100000,
                "ip_limit": {
                    "enabled": True,
                    "max_ips": 1,
                    "lease_seconds": 60,
                    "ban_seconds": 30,
                    "mode": "reject_new",
                },
            },
        )
        response = await self.client.patch(
            f"/v1/admin/plans/{plan['id']}/active",
            headers=self.headers,
            json={"is_active": True},
        )
        self.assertEqual(response.status_code, 200)
        detail = (await self.get(f"/v1/admin/plans/{plan['id']}"))["data"]
        self.assertEqual(detail["id"], plan["id"])
        self.assertNotIn("ip_limit_json", detail)
        await self.trial_policy(
            enabled=True,
            plan_id=plan["id"],
            quota_bytes=123456,
            duration_days=2,
        )
        return plan

    async def trial_policy(self, **changes):
        prefs = (await self.get("/v1/admin/settings"))["data"]
        prefs["values"]["trials"].update(changes)
        response = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": prefs["revision"],
                "values": prefs["values"],
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    async def test_owned_trial_replay_concurrent_cap_and_no_money(self):
        await self.source()
        missing = await self.client.post(
            "/v1/admin/customers/9223372036854775807/trial",
            headers=self.headers,
            json={"request_key": uuid4().hex},
        )
        self.assertEqual(missing.status_code, 404)
        client, headers, customer_id = await self.account()
        other, other_headers, other_id = await self.account()
        try:
            self.assertTrue(
                (await client.get("/v1/customer/trials/availability")).json()[
                    "data"
                ]["eligible"]
            )
            self.assertEqual(
                (
                    await client.post(
                        "/v1/customer/trials",
                        json={"request_key": uuid4().hex},
                    )
                ).status_code,
                403,
            )

            async def claim(key):
                response = await client.post(
                    "/v1/customer/trials",
                    headers=headers,
                    json={"request_key": key, "customer_id": other_id},
                )
                return key, response

            results = await asyncio.gather(
                asyncio.create_task(claim(uuid4().hex), context=Context()),
                asyncio.create_task(claim(uuid4().hex), context=Context()),
            )
            self.assertEqual(
                sorted(response.status_code for _, response in results),
                [200, 409],
            )
            key, created = next(
                (key, response)
                for key, response in results
                if response.status_code == 200
            )
            sub = created.json()["data"]
            self.assertEqual(
                (
                    sub["customer_id"],
                    sub["entitlement_kind"],
                    sub["price_rial"],
                    sub["quota_bytes"],
                    sub["duration_days"],
                    sub["status"],
                    sub["auto_renew"],
                ),
                (
                    customer_id,
                    "trial",
                    0,
                    123456,
                    2,
                    "pending_provision",
                    False,
                ),
            )
            self.assertNotIn("trial_policy_json", sub)
            await self.trial_policy(enabled=False, quota_bytes=789)
            replay = await client.post(
                "/v1/customer/trials",
                headers=headers,
                json={"request_key": key},
            )
            self.assertEqual(replay.json()["data"]["id"], sub["id"])
            self.assertEqual(replay.json()["data"]["quota_bytes"], 123456)
            self.assertEqual(
                (
                    await other.get(f"/v1/customer/subscriptions/{sub['id']}")
                ).status_code,
                404,
            )
            renewal_responses = await asyncio.gather(
                self.client.patch(
                    f"/v1/admin/subscriptions/{sub['id']}/auto-renew",
                    headers=self.headers,
                    json={"enabled": True},
                ),
                client.patch(
                    f"/v1/customer/subscriptions/{sub['id']}/auto-renew",
                    headers=headers,
                    json={"enabled": True},
                ),
            )
            self.assertTrue(
                all(row.status_code == 409 for row in renewal_responses)
            )
            async with self.connection.uow() as unit:
                counts = (
                    await unit.execute(
                        text(
                            "SELECT "
                            "(SELECT COUNT(*) FROM tbl_wallet_entries), "
                            "(SELECT COUNT(*) FROM tbl_wallets), "
                            "(SELECT COUNT(*) FROM tbl_provision_requests), "
                            "(SELECT COUNT(*) FROM tbl_ip_limit_policies)"
                        )
                    )
                ).one()
                self.assertEqual(tuple(counts), (0, 0, 1, 1))
            readonly = await self.post(
                "/v1/admin/staff",
                {
                    "username": "trialreader_" + self.suffix,
                    "password": "reader888",
                    "is_active": True,
                    "scopes": ["subscriptions:read", "customers:read"],
                },
            )
            reader, reader_headers = await self.login_staff(
                readonly["username"], "reader888"
            )
            try:
                self.assertEqual(
                    (
                        await reader.get(
                            f"/v1/admin/customers/{customer_id}/trial-availability"
                        )
                    ).status_code,
                    200,
                )
                self.assertEqual(
                    (
                        await reader.post(
                            f"/v1/admin/customers/{customer_id}/trial",
                            headers=reader_headers,
                            json={"request_key": uuid4().hex},
                        )
                    ).status_code,
                    403,
                )
            finally:
                await reader.aclose()
        finally:
            await client.aclose()
            await other.aclose()

    async def test_trial_modes_failure_recovery_paid_eligibility_and_bot(
        self,
    ):
        plan = await self.source()
        client, headers, customer_id = await self.account()
        try:
            # Failed uncharged trials must not create wallet credit.
            sub = (
                await client.post(
                    "/v1/customer/trials",
                    headers=headers,
                    json={"request_key": uuid4().hex},
                )
            ).json()["data"]
            failed = await self.post(
                f"/v1/admin/subscriptions/{sub['id']}/provision-failed",
                {"reason": "لغو آزمایش بدون راه‌اندازی"},
            )
            self.assertEqual(failed["status"], "failed")
            async with self.connection.uow() as unit:
                self.assertEqual(
                    (
                        await unit.execute(
                            text("SELECT COUNT(*) FROM tbl_wallet_entries")
                        )
                    ).scalar_one(),
                    0,
                )
                self.assertEqual(
                    (
                        await unit.execute(
                            text("SELECT COUNT(*) FROM tbl_wallets")
                        )
                    ).scalar_one(),
                    0,
                )
            await self.trial_policy(
                max_claims_per_customer=3, cooldown_seconds=3600
            )
            offer = (
                await client.get("/v1/customer/trials/availability")
            ).json()["data"]
            self.assertEqual(offer["reason"], "trial_cooldown")
            self.assertTrue(
                offer["next_claim_at"].endswith("Z")
                or offer["next_claim_at"].endswith("+00:00")
            )
            await self.trial_policy(cooldown_seconds=0)
            second = await client.post(
                "/v1/customer/trials",
                headers=headers,
                json={"request_key": uuid4().hex},
            )
            self.assertEqual(second.status_code, 200)
            self.assertEqual(
                (await client.get("/v1/customer/trials/availability")).json()[
                    "data"
                ]["reason"],
                "trial_active_exists",
            )
            await self.trial_policy(concurrent_mode="allow_multiple")
            self.assertEqual(
                (
                    await client.post(
                        "/v1/customer/trials",
                        headers=headers,
                        json={"request_key": uuid4().hex},
                    )
                ).status_code,
                200,
            )
            self.assertEqual(
                (await client.get("/v1/customer/trials/availability")).json()[
                    "data"
                ]["reason"],
                "trial_claim_limit",
            )
            self.settings.trials.max_quota_bytes = 1
            self.assertFalse(
                (await client.get("/v1/customer/trials/availability")).json()[
                    "data"
                ]["capacity_valid"]
            )
            self.settings.trials.max_quota_bytes = self.raw["trials"][
                "max_quota_bytes"
            ]
            identity = {
                "telegram_id": int(uuid4().hex[:12], 16),
                "display_name": "آزمایشی بات",
            }
            bot_headers = {
                "X-Papilio-Bot-Key": self.settings.security.bot_service_key
            }
            self.assertEqual(
                (
                    await self.client.post(
                        "/v1/bot/trials",
                        json={**identity, "request_key": uuid4().hex},
                    )
                ).status_code,
                401,
            )
            bot_key = uuid4().hex
            bot = await self.client.post(
                "/v1/bot/trials",
                headers=bot_headers,
                json={**identity, "request_key": bot_key},
            )
            self.assertEqual(bot.status_code, 200)
            self.assertEqual(
                (
                    await self.client.post(
                        "/v1/bot/trials",
                        headers=bot_headers,
                        json={**identity, "request_key": bot_key},
                    )
                ).json()["data"]["id"],
                bot.json()["data"]["id"],
            )
            paying = await self.post(
                "/v1/admin/customers", {"display_name": "مشتری پولی"}
            )
            topup = await self.post(
                "/v1/admin/payments/topups",
                {"customer_id": paying["id"], "amount_rial": 100000},
            )
            await self.post(
                f"/v1/admin/payments/topups/{topup['id']}/approve",
                {
                    "expected_revision": 1,
                    "bank_reference": "trialpay_" + uuid4().hex,
                },
            )
            paid = await self.post(
                "/v1/admin/subscriptions",
                {
                    "customer_id": paying["id"],
                    "plan_id": plan["id"],
                    "purchase_key": uuid4().hex,
                },
            )
            self.assertEqual(paid["entitlement_kind"], "paid")
            self.assertEqual(
                (
                    await self.get(
                        f"/v1/admin/customers/{paying['id']}/trial-availability"
                    )
                )["data"]["reason"],
                "trial_paid_customer",
            )
            await self.trial_policy(eligibility="any_customer")
            self.assertTrue(
                (
                    await self.get(
                        f"/v1/admin/customers/{paying['id']}/trial-availability"
                    )
                )["data"]["eligible"]
            )
        finally:
            await client.aclose()

    async def test_prior_paid_data_sessions_and_legacy_preferences_upgrade(
        self,
    ):
        customer, paid = await self.paid_subscription()
        await self.post(
            f"/v1/admin/subscriptions/attention/{paid['id']}/check"
        )
        attention_before = (
            await self.get(
                f"/v1/admin/subscriptions/attention?customer_id={customer['id']}"
            )
        )["data"][0]
        prefs = (await self.get("/v1/admin/settings"))["data"]
        prefs["values"].pop("trials")
        saved = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": prefs["revision"],
                "values": prefs["values"],
            },
        )
        self.assertEqual(saved.status_code, 200)
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    update(PreferencesRevisionTable)
                    .where(
                        PreferencesRevisionTable.revision
                        == saved.json()["data"]["revision"]
                    )
                    .values(values_json=json.dumps(prefs["values"]))
                )
            before = tuple(
                (
                    await unit.execute(
                        text(
                            "SELECT (SELECT COUNT(*) FROM tbl_customers), "
                            "(SELECT COUNT(*) FROM tbl_subscriptions), "
                            "(SELECT COUNT(*) FROM tbl_wallet_entries), "
                            "(SELECT COUNT(*) FROM tbl_notifications)"
                        )
                    )
                ).one()
            )
        assert self.settings.db is not None
        migration = Config("alembic.ini")
        migration.set_main_option(
            "sqlalchemy.url",
            make_url(str(self.settings.db.dsn)).render_as_string(
                hide_password=False
            ),
        )
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(
                command.downgrade, migration, "0029_notifications"
            )
            await asyncio.to_thread(command.upgrade, migration, "head")
        self.assertEqual(
            (await self.client.get("/v1/admin/auth/me")).status_code, 200
        )
        retained = (await self.get(f"/v1/admin/subscriptions/{paid['id']}"))[
            "data"
        ]
        self.assertEqual(
            (
                retained["entitlement_kind"],
                retained["customer_id"],
                retained["price_rial"],
            ),
            ("paid", customer["id"], 100000),
        )
        self.assertEqual(retained["payer_customer_id"], customer["id"])
        self.assertIsNone(retained["reseller_id"])
        self.assertIsNone(retained["reseller_billing"])
        attention_after = (
            await self.get(
                f"/v1/admin/subscriptions/attention?customer_id={customer['id']}"
            )
        )["data"][0]
        self.assertEqual(
            attention_after["wallet_balance_rial"],
            attention_before["wallet_balance_rial"],
        )
        self.assertEqual(
            attention_after["checked_at"], attention_before["checked_at"]
        )
        self.assertIsNone(attention_after["payer_customer_id"])
        self.assertIsNone(attention_after["renewal_price_rial"])
        self.assertIsNone(attention_after["renewal_available"])
        self.assertFalse(
            (await self.get("/v1/admin/settings"))["data"]["values"]["trials"][
                "enabled"
            ]
        )
        async with self.connection.uow() as unit:
            payer = (
                await unit.execute(
                    text(
                        "SELECT payer_customer_id, reseller_id, "
                        "reseller_agreement_id, reseller_billing_json "
                        "FROM tbl_subscriptions WHERE id=:id"
                    ),
                    {"id": paid["id"]},
                )
            ).one()
            self.assertEqual(tuple(payer), (customer["id"], None, None, None))
            after = tuple(
                (
                    await unit.execute(
                        text(
                            "SELECT (SELECT COUNT(*) FROM tbl_customers), "
                            "(SELECT COUNT(*) FROM tbl_subscriptions), "
                            "(SELECT COUNT(*) FROM tbl_wallet_entries), "
                            "(SELECT COUNT(*) FROM tbl_notifications)"
                        )
                    )
                ).one()
            )
            self.assertEqual(after, before)

    async def test_trial_acknowledged_delivery_and_native_expiry_no_refund(
        self,
    ):
        from datetime import UTC, datetime, timedelta

        from src.modules.sales.subscriptions.infra.tables import (
            SubscriptionTable,
        )
        from tests.scheduler_runtime import exercise_native_lifecycle

        paid, _, nodes, purchase = await FulfillmentWorkflowFixture.setup_sale(
            self, protocols=("vless_reality",)
        )
        await self.trial_policy(
            enabled=True,
            plan_id=purchase["plan_id"],
            quota_bytes=765432,
            duration_days=1,
        )
        client, headers, customer_id = await self.account()
        try:
            sub = (
                await client.post(
                    "/v1/customer/trials",
                    headers=headers,
                    json={"request_key": uuid4().hex},
                )
            ).json()["data"]
            sid = sub["id"]
            request = (
                await self.get(f"/v1/admin/provisioning?subscription_id={sid}")
            )["data"][0]
            await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
            task = (
                await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
            )["data"][0]
            node, claim = await FulfillmentWorkflowFixture.claim(
                self, task, nodes
            )
            await FulfillmentWorkflowFixture.ack(self, task, node, claim)
            active = (await self.get(f"/v1/admin/subscriptions/{sid}"))["data"]
            self.assertEqual(
                (
                    active["status"],
                    active["quota_bytes"],
                    active["entitlement_kind"],
                ),
                ("active", 765432, "trial"),
            )
            delivery = (
                await client.get(f"/v1/customer/subscriptions/{sid}/delivery")
            ).json()["data"]
            self.assertEqual(delivery["entitlement_kind"], "trial")
            self.assertIsNotNone(delivery["feed_url"])
            async with self.connection.uow() as unit:
                async with transaction(unit):
                    await unit.execute(
                        update(SubscriptionTable)
                        .where(SubscriptionTable.id == sid)
                        .values(
                            expires_at=datetime.now(UTC).replace(tzinfo=None)
                            - timedelta(minutes=1)
                        )
                    )
                    # Disable unrelated paid renewal during the expiry gate.
                    await unit.execute(
                        update(SubscriptionTable)
                        .where(SubscriptionTable.id == paid["id"])
                        .values(auto_renew=False)
                    )
                before = (
                    await unit.execute(
                        text("SELECT COUNT(*) FROM tbl_wallet_entries")
                    )
                ).scalar_one()
            await asyncio.to_thread(exercise_native_lifecycle, self.raw, sid)
            self.assertEqual(
                (await self.get(f"/v1/admin/subscriptions/{sid}"))["data"][
                    "status"
                ],
                "revoking",
            )
            revoke = (
                await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
            )["data"][0]
            self.assertEqual(revoke["action"], "revoke")
            node, claim = await FulfillmentWorkflowFixture.claim(
                self, revoke, nodes
            )
            await FulfillmentWorkflowFixture.ack(
                self, revoke, node, claim, outcome="revoked"
            )
            expired = (await self.get(f"/v1/admin/subscriptions/{sid}"))[
                "data"
            ]
            self.assertEqual(
                (expired["status"], expired["renewal_count"]), ("expired", 0)
            )
            self.assertIsNone(
                (
                    await client.get(
                        f"/v1/customer/subscriptions/{sid}/delivery"
                    )
                ).json()["data"]["feed_url"]
            )
            async with self.connection.uow() as unit:
                after = (
                    await unit.execute(
                        text("SELECT COUNT(*) FROM tbl_wallet_entries")
                    )
                ).scalar_one()
                self.assertEqual(after, before)
                self.assertEqual(
                    (
                        await unit.execute(
                            text(
                                "SELECT COUNT(*) FROM tbl_wallets "
                                "WHERE customer_id=:id"
                            ),
                            {"id": customer_id},
                        )
                    ).scalar_one(),
                    0,
                )
        finally:
            await client.aclose()
