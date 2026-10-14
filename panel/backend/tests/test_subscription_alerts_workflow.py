import asyncio
from datetime import UTC, datetime, timedelta

from papilio.infra.db.transaction import transaction
from sqlalchemy import select, update
from sqlmodel import col

from src.modules.operations.notifications.infra.tables import NotificationTable
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable
from tests.scheduler_runtime import _exercise_native_runtime
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowFixture,
)


def exercise_subscription_alerts(raw, subscription_id):
    return _exercise_native_runtime(
        raw,
        "SELECT COUNT(*) total, "
        "SUM(subscription_context IS NOT NULL) captured "
        "FROM tbl_notifications WHERE record_id=%s AND kind='volume_low'",
        (subscription_id,),
        lambda row: row["total"] == 2 and row["captured"] == 2,
        ("total", "captured"),
        ("ScanSubscriptionAttention", "CheckSubscriptionAttention"),
    )


class SubscriptionAlertsWorkflowTest(StaffAdministrationWorkflowFixture):
    async def configure_alerts(self):
        prefs = (await self.get("/v1/admin/settings"))["data"]
        prefs["values"]["subscription_alerts"] = {
            "enabled": True,
            "low_quota": [
                {
                    "code": "percentage",
                    "mode": "any",
                    "remaining_percent_bps": 2000,
                    "remaining_bytes": None,
                },
                {
                    "code": "combined",
                    "mode": "all",
                    "remaining_percent_bps": 3000,
                    "remaining_bytes": 300000000,
                },
            ],
            "expiry_hours": [24],
            "renewal_opportunity": True,
        }
        prefs["values"]["notifications"].update(
            enabled=True, channel_mode="inbox"
        )
        prefs["values"]["notifications"]["templates"].update(
            volume_low={
                "enabled": True,
                "title": "Low quota {id}",
                "body": (
                    "{remaining_gib} of {quota_gib}; used {used_gib}; "
                    "{threshold_code}; generation {generation}; "
                    "{renewal_price_toman}"
                ),
            },
            renewal_available={
                "enabled": True,
                "title": "Renewal {id}",
                "body": "{renewal_price_toman} {expires_at}",
            },
            expiry_soon={
                "enabled": True,
                "title": "Expiry {id}",
                "body": "{expires_at}",
            },
        )
        result = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": prefs["revision"],
                "values": prefs["values"],
            },
        )
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()["data"]

    async def change(self, subscription_id, **values):
        async with self.connection.uow() as unit:
            async with transaction():
                await unit.execute(
                    update(SubscriptionTable)
                    .where(col(SubscriptionTable.id) == subscription_id)
                    .values(**values)
                )

    async def notices(self, customer_id):
        response = await self.client.get(
            "/v1/admin/notifications",
            params={"customer_id": customer_id},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    async def test_scheduler_rules_replay_generation_and_null_plan_modes(self):
        await self.configure_alerts()
        customer, subscription = await self.paid_subscription()
        await self.change(
            subscription["id"], status="active", used_bytes=850000000
        )
        self.raw["operations"]["subscription_attention_scan_cron"] = (
            "* * * * *"
        )
        result = await asyncio.to_thread(
            exercise_subscription_alerts, self.raw, subscription["id"]
        )
        self.assertEqual(result, (2, 2))
        notices = await self.notices(customer["id"])
        quota = [row for row in notices if row["kind"] == "volume_low"]
        self.assertEqual(len(quota), 2)
        self.assertTrue(
            all(
                row["subscription_context"]["remaining_bytes"] == 150000000
                for row in quota
            )
        )
        first = {row["id"]: row["subscription_context"] for row in quota}
        await self.change(subscription["id"], used_bytes=950000000)
        left, right = await asyncio.gather(
            self.post(
                f"/v1/admin/subscriptions/attention/{subscription['id']}/check"
            ),
            self.post(
                f"/v1/admin/subscriptions/attention/{subscription['id']}/check"
            ),
        )
        self.assertEqual(left["subscription_id"], right["subscription_id"])
        fresh = await self.notices(customer["id"])
        self.assertEqual(
            {
                row["id"]: row["subscription_context"]
                for row in fresh
                if row["kind"] == "volume_low"
            },
            first,
        )
        await self.change(subscription["id"], renewal_count=1)
        await self.post(
            f"/v1/admin/subscriptions/attention/{subscription['id']}/check"
        )
        fresh = await self.notices(customer["id"])
        self.assertEqual(
            len([row for row in fresh if row["kind"] == "volume_low"]), 4
        )
        await self.change(
            subscription["id"],
            renewal_count=2,
            quota_bytes=None,
            expires_at=None,
        )
        await self.post(
            f"/v1/admin/subscriptions/attention/{subscription['id']}/check"
        )
        fresh = await self.notices(customer["id"])
        self.assertFalse(
            any(
                row["subscription_context"]
                and row["subscription_context"]["generation"] == 2
                for row in fresh
            )
        )
        await self.change(
            subscription["id"],
            renewal_count=3,
            quota_bytes=None,
            expires_at=datetime.now(UTC).replace(tzinfo=None)
            + timedelta(hours=1),
        )
        await self.post(
            f"/v1/admin/subscriptions/attention/{subscription['id']}/check"
        )
        fresh = await self.notices(customer["id"])
        expiry = [row for row in fresh if row["kind"] == "expiry_soon"]
        self.assertEqual(len(expiry), 1)
        self.assertIsNone(expiry[0]["subscription_context"]["quota_bytes"])
        async with self.connection.uow() as independent:
            persisted = await independent.execute(
                select(NotificationTable).where(
                    col(NotificationTable.id) == quota[0]["id"]
                )
            )
            row = persisted.scalar_one()
            assert row.subscription_context is not None
            self.assertEqual(
                row.subscription_context["remaining_bytes"], 150000000
            )

    async def test_policy_capacity_and_legacy_placeholder_compatibility(self):
        snapshot = await self.configure_alerts()
        policy = snapshot["values"]["subscription_alerts"]
        assert policy is not None
        policy["expiry_hours"] = [
            self.settings.subscription_alerts_capacity.max_expiry_hours + 1
        ]
        rejected = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": snapshot["revision"],
                "values": snapshot["values"],
            },
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(
            rejected.json()["error"]["message_code"],
            "subscription_alert_capacity",
        )
        snapshot = (await self.get("/v1/admin/settings"))["data"]
        snapshot["values"]["subscription_alerts"]["low_quota"] = [
            {"code": f"rule{i}", "mode": "any", "remaining_bytes": 0}
            for i in range(
                self.settings.subscription_alerts_capacity.max_low_quota_rules
                + 1
            )
        ]
        rejected = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": snapshot["revision"],
                "values": snapshot["values"],
            },
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(
            rejected.json()["error"]["message_code"],
            "subscription_alert_capacity",
        )
        snapshot = (await self.get("/v1/admin/settings"))["data"]
        snapshot["values"]["subscription_alerts"] = None
        snapshot["values"]["notifications"]["templates"][
            "payment_approved"
        ] = {
            "enabled": True,
            "title": "Paid",
            "body": (
                "{amount_toman} {remaining_gib} {expires_at} "
                "{renewal_price_toman}"
            ),
        }
        saved = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": snapshot["revision"],
                "values": snapshot["values"],
            },
        )
        self.assertEqual(saved.status_code, 200)
        customer, _ = await self.paid_subscription()
        rows = await self.notices(customer["id"])
        payment = [row for row in rows if row["kind"] == "payment_approved"]
        self.assertEqual(len(payment), 1)
        self.assertIsNone(payment[0]["subscription_context"])

    async def test_owned_renewal_quotes_payer_privacy_and_unavailable_plan(
        self,
    ):
        from uuid import uuid4

        import httpx

        from src.modules.accounts.customers.infra.tables import CustomerTable

        snapshot = (await self.get("/v1/admin/settings"))["data"]
        snapshot["values"]["fulfillment"]["renewal_price"] = "current_plan"
        saved = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": snapshot["revision"],
                "values": snapshot["values"],
            },
        )
        self.assertEqual(saved.status_code, 200)
        customer, subscription = await self.paid_subscription(auto_renew=True)
        telegram_id = int(uuid4().hex[:12], 16)
        identity = {
            "telegram_id": telegram_id,
            "display_name": customer["display_name"],
        }
        async with self.connection.uow() as unit:
            async with transaction():
                await unit.execute(
                    update(CustomerTable)
                    .where(col(CustomerTable.id) == customer["id"])
                    .values(telegram_id=telegram_id)
                )
        await self.change(subscription["id"], status="active")
        bot_headers = {
            "X-Papilio-Bot-Key": self.settings.security.bot_service_key
        }
        link = await self.client.post(
            "/v1/bot/account-link", headers=bot_headers, json=identity
        )
        self.assertEqual(link.status_code, 200)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url=self.settings.public.customer_portal_origin,
        ) as client:
            session = await client.post(
                "/v1/customer/auth/exchange",
                headers={
                    "Origin": self.settings.public.customer_portal_origin
                },
                json={"token": link.json()["data"]["url"].rsplit("#", 1)[-1]},
            )
            self.assertEqual(session.status_code, 200)
            path = (
                f"/v1/customer/subscriptions/{subscription['id']}"
                "/renewal-eligibility"
            )
            own = await client.get(path)
            self.assertEqual(own.status_code, 200, own.text)
            quote = own.json()["data"]
            self.assertEqual(quote["payer_kind"], "self")
            self.assertTrue(quote["eligible"])
            self.assertTrue(quote["auto_renew_authorized"])
            self.assertFalse(quote["renewal_due"])
            self.assertEqual(quote["wallet_balance_rial"], 200000)
            payer = await self.post(
                "/v1/admin/customers",
                {"display_name": "Other payer " + self.suffix},
            )
            await self.change(
                subscription["id"], payer_customer_id=payer["id"]
            )
            other = await client.get(path)
            self.assertEqual(other.status_code, 200)
            projection = other.json()["data"]
            self.assertEqual(projection["payer_kind"], "other")
            self.assertIsNone(projection["wallet_balance_rial"])
            self.assertIsNone(projection["wallet_shortfall_rial"])
            self.assertIsNone(projection["wallet_funded"])
            self.assertNotIn("payer_customer_id", projection)
            bot = await self.client.post(
                f"/v1/bot/subscriptions/{subscription['id']}/renewal-eligibility",
                headers=bot_headers,
                json=identity,
            )
            self.assertEqual(bot.status_code, 200)
            self.assertEqual(bot.json()["data"]["payer_kind"], "other")
            foreign = await self.client.post(
                f"/v1/bot/subscriptions/{subscription['id']}/renewal-eligibility",
                headers=bot_headers,
                json={**identity, "telegram_id": telegram_id + 1},
            )
            self.assertEqual(foreign.status_code, 404)
            await self.change(
                subscription["id"],
                payer_customer_id=customer["id"],
                expires_at=datetime.now(UTC).replace(tzinfo=None)
                - timedelta(hours=1),
                status="expired",
            )
            disabled = await self.client.patch(
                f"/v1/admin/plans/{subscription['plan_id']}/active",
                headers=self.headers,
                json={"is_active": False},
            )
            self.assertEqual(disabled.status_code, 200)
            unavailable = await client.get(path)
            self.assertEqual(unavailable.status_code, 200)
            self.assertFalse(unavailable.json()["data"]["quote_available"])
            self.assertFalse(unavailable.json()["data"]["eligible"])
            self.assertTrue(unavailable.json()["data"]["renewal_due"])

    async def test_populated_0046_upgrade_and_context_loss_refusal(
        self,
    ):
        import hashlib
        import json

        from alembic import command
        from alembic.config import Config
        from sqlalchemy import text

        customer, subscription = await self.paid_subscription()
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", self.raw["db"]["dsn"])
        await asyncio.to_thread(
            command.downgrade, cfg, "0046_core_memberships"
        )
        tables = (
            "tbl_staff",
            "tbl_wallets",
            "tbl_wallet_entries",
            "tbl_topups",
            "tbl_notifications",
        )

        async def snapshot(table, columns=None):
            async with self.connection.uow() as independent:
                if columns is None:
                    result = await independent.execute(
                        text(f"SHOW COLUMNS FROM {table}")
                    )
                    columns = [row[0] for row in result.all()]
                selected = ",".join(f"`{column}`" for column in columns)
                result = await independent.execute(
                    text(f"SELECT {selected} FROM {table} ORDER BY id")
                )
                rows = [tuple(row) for row in result.all()]
            digest = await asyncio.to_thread(
                lambda: hashlib.sha256(
                    json.dumps(rows, default=str, ensure_ascii=False).encode()
                ).hexdigest()
            )
            return columns, len(rows), digest

        before = await asyncio.gather(*(snapshot(table) for table in tables))
        self.assertTrue(all(count > 0 for _, count, _ in before))
        await asyncio.to_thread(
            command.upgrade, cfg, "0047_subscription_notice_context"
        )
        after = await asyncio.gather(
            *(
                snapshot(table, columns=old[0])
                for table, old in zip(tables, before, strict=True)
            )
        )
        self.assertEqual(
            [row[1:] for row in before], [row[1:] for row in after]
        )
        async with self.connection.uow() as independent:
            result = await independent.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_notifications "
                    "WHERE subscription_context IS NOT NULL"
                )
            )
            self.assertEqual(result.scalar_one(), 0)
        await self.configure_alerts()
        await self.change(
            subscription["id"], status="active", used_bytes=950000000
        )
        await self.post(
            f"/v1/admin/subscriptions/attention/{subscription['id']}/check"
        )
        old_notices = await self.notices(customer["id"])
        self.assertTrue(
            any(
                row["kind"] == "payment_approved"
                and row["subscription_context"] is None
                for row in old_notices
            )
        )
        contexts = [
            row["subscription_context"]
            for row in old_notices
            if row["subscription_context"] is not None
        ]
        self.assertEqual(len(contexts), 3)
        current = await snapshot("tbl_notifications")
        with self.assertRaisesRegex(
            RuntimeError, "lose immutable subscription alert context"
        ):
            await asyncio.to_thread(
                command.downgrade, cfg, "0046_core_memberships"
            )
        preserved = await snapshot("tbl_notifications")
        self.assertEqual(current[1:], preserved[1:])
        protected = await asyncio.gather(
            *(
                snapshot(table, columns=old[0])
                for table, old in zip(tables[:-1], before[:-1], strict=True)
            )
        )
        self.assertEqual(
            [row[1:] for row in before[:-1]], [row[1:] for row in protected]
        )
        restored = await self.notices(customer["id"])
        self.assertEqual(
            [
                row["subscription_context"]
                for row in restored
                if row["subscription_context"] is not None
            ],
            contexts,
        )
        alive = await self.get("/v1/admin/auth/me")
        self.assertEqual(alive["username"], self.username)

    async def test_optional_template_removal_preserves_notice_attempts(
        self,
    ):
        from src.config.settings import NotificationSettings
        from src.modules.accounts.customers.infra.tables import CustomerTable
        from src.modules.operations.notifications.interfaces import (
            INotificationDeliveryCommand,
        )

        snapshot = await self.configure_alerts()
        snapshot["values"]["notifications"].update(
            channel_mode="both", delivery_enabled=True
        )
        saved = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": snapshot["revision"],
                "values": snapshot["values"],
            },
        )
        self.assertEqual(saved.status_code, 200)
        transport = self.settings.notifications.model_dump()
        transport.update(
            outbound_enabled=True,
            endpoint="http://127.0.0.1:54321/deliver",
            delivery_key="template-removal-test-key-native-guard",
            allow_loopback_http=True,
        )
        self.settings.notifications = NotificationSettings.model_validate(
            transport
        )
        customer, subscription = await self.paid_subscription()
        async with self.connection.uow() as unit:
            async with transaction():
                await unit.execute(
                    update(CustomerTable)
                    .where(col(CustomerTable.id) == customer["id"])
                    .values(telegram_id=613141)
                )
        await self.change(
            subscription["id"], status="active", used_bytes=950000000
        )
        await self.post(
            f"/v1/admin/subscriptions/attention/{subscription['id']}/check"
        )
        notices = [
            row
            for row in await self.notices(customer["id"])
            if row["kind"] == "volume_low"
        ]
        self.assertEqual(len(notices), 2)
        async with self.app.state.dishka_container() as scope:
            command = await scope.get(INotificationDeliveryCommand)
            claim = await command.claim(notices[0]["id"])
        self.assertIsNotNone(claim)
        snapshot = (await self.get("/v1/admin/settings"))["data"]
        template = snapshot["values"]["notifications"]["templates"].pop(
            "volume_low"
        )
        removed = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": snapshot["revision"],
                "values": snapshot["values"],
            },
        )
        self.assertEqual(removed.status_code, 200)
        authorization = await self.client.post(
            f"/v1/bot/notifications/{claim.notification_id}/authorize",
            headers={
                "X-Papilio-Bot-Key": self.settings.security.bot_service_key
            },
            json={"claim_token": claim.claim_token},
        )
        self.assertEqual(authorization.status_code, 200)
        self.assertFalse(authorization.json()["data"]["allowed"])
        async with self.app.state.dishka_container() as scope:
            command = await scope.get(INotificationDeliveryCommand)
            pending = await command.claim(notices[1]["id"])
        self.assertIsNone(pending)
        preserved = await self.notices(customer["id"])
        attempts = {row["id"]: row["attempts"] for row in preserved}
        self.assertEqual(attempts[notices[0]["id"]], 1)
        self.assertEqual(attempts[notices[1]["id"]], 0)
        snapshot = removed.json()["data"]
        snapshot["values"]["notifications"]["templates"]["volume_low"] = (
            template
        )
        restored = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": snapshot["revision"],
                "values": snapshot["values"],
            },
        )
        self.assertEqual(restored.status_code, 200)
        authorized = await self.client.post(
            f"/v1/bot/notifications/{claim.notification_id}/authorize",
            headers={
                "X-Papilio-Bot-Key": self.settings.security.bot_service_key
            },
            json={"claim_token": claim.claim_token},
        )
        self.assertEqual(authorized.status_code, 200)
        self.assertTrue(authorized.json()["data"]["allowed"])
        duplicate = await self.client.post(
            f"/v1/bot/notifications/{claim.notification_id}/authorize",
            headers={
                "X-Papilio-Bot-Key": self.settings.security.bot_service_key
            },
            json={"claim_token": claim.claim_token},
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertFalse(duplicate.json()["data"]["allowed"])
        async with self.app.state.dishka_container() as scope:
            command = await scope.get(INotificationDeliveryCommand)
            admitted = await command.claim(notices[1]["id"])
        self.assertIsNotNone(admitted)
        self.assertEqual(admitted.telegram_id, 613141)

    async def test_readiness_uses_current_wallet_after_held_rr_view(self):
        from contextvars import Context

        from papilio.infra.db.uow import MySQLUnitOfWork

        from src.modules.billing.wallet.infra.tables import WalletTable
        from src.modules.sales.attention.interfaces import (
            ICustomerRenewalEligibilityQuery,
        )

        customer, subscription = await self.paid_subscription()
        await self.change(subscription["id"], status="active")
        async with self.app.state.dishka_container() as scope:
            unit = await scope.get(MySQLUnitOfWork)
            query = await scope.get(ICustomerRenewalEligibilityQuery)
            async with transaction(unit):
                old = await unit.execute(
                    select(WalletTable).where(
                        col(WalletTable.customer_id) == customer["id"]
                    )
                )
                self.assertEqual(old.scalar_one().balance_rial, 200000)
                charged = await asyncio.create_task(
                    self.post(
                        "/v1/admin/subscriptions",
                        {
                            "customer_id": customer["id"],
                            "plan_id": subscription["plan_id"],
                            "purchase_key": "rr-wallet-" + self.suffix,
                            "auto_renew": False,
                        },
                    ),
                    context=Context(),
                )
                self.assertEqual(charged["price_rial"], 100000)
                projection = await query.get(
                    subscription["id"], customer["id"]
                )
                self.assertEqual(projection.wallet_balance_rial, 100000)
                self.assertEqual(projection.wallet_shortfall_rial, 0)
        wallet = (
            await self.get(f"/v1/admin/payments/wallets/{customer['id']}")
        )["data"]
        self.assertEqual(
            wallet["balance_rial"], projection.wallet_balance_rial
        )

    async def test_readiness_uses_current_plan_price_after_held_rr_view(self):
        from contextvars import Context

        from papilio.infra.db.uow import MySQLUnitOfWork

        from src.modules.sales.attention.interfaces import (
            ICustomerRenewalEligibilityQuery,
        )
        from src.modules.sales.catalog.infra.tables import PlanTable

        snapshot = (await self.get("/v1/admin/settings"))["data"]
        snapshot["values"]["fulfillment"]["renewal_price"] = "current_plan"
        saved = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": snapshot["revision"],
                "values": snapshot["values"],
            },
        )
        self.assertEqual(saved.status_code, 200)
        customer, subscription = await self.paid_subscription()
        await self.change(subscription["id"], status="active")
        async with self.app.state.dishka_container() as scope:
            unit = await scope.get(MySQLUnitOfWork)
            query = await scope.get(ICustomerRenewalEligibilityQuery)
            async with transaction(unit):
                old = await unit.execute(
                    select(PlanTable).where(
                        col(PlanTable.id) == subscription["plan_id"]
                    )
                )
                old_plan = old.scalar_one()
                self.assertEqual(old_plan.price_rial, 100000)
                changed = await asyncio.create_task(
                    self.client.patch(
                        f"/v1/admin/plans/{subscription['plan_id']}",
                        headers=self.headers,
                        json={"price_rial": 250000},
                    ),
                    context=Context(),
                )
                self.assertEqual(changed.status_code, 200)
                projection = await query.get(
                    subscription["id"], customer["id"]
                )
                self.assertEqual(projection.renewal_price_rial, 250000)
                self.assertEqual(projection.wallet_shortfall_rial, 50000)
                self.assertFalse(projection.wallet_funded)
        self.assertEqual(
            (await self.get(f"/v1/admin/plans/{subscription['plan_id']}"))[
                "data"
            ]["price_rial"],
            250000,
        )

    async def test_readiness_rejects_disabled_plan_after_held_rr_view(self):
        from contextvars import Context

        from papilio.infra.db.uow import MySQLUnitOfWork

        from src.modules.sales.attention.interfaces import (
            ICustomerRenewalEligibilityQuery,
        )
        from src.modules.sales.catalog.infra.tables import PlanTable

        snapshot = (await self.get("/v1/admin/settings"))["data"]
        snapshot["values"]["fulfillment"]["renewal_price"] = "current_plan"
        saved = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": snapshot["revision"],
                "values": snapshot["values"],
            },
        )
        self.assertEqual(saved.status_code, 200)
        customer, subscription = await self.paid_subscription()
        await self.change(subscription["id"], status="active")
        async with self.app.state.dishka_container() as scope:
            unit = await scope.get(MySQLUnitOfWork)
            query = await scope.get(ICustomerRenewalEligibilityQuery)
            async with transaction(unit):
                old = await unit.execute(
                    select(PlanTable).where(
                        col(PlanTable.id) == subscription["plan_id"]
                    )
                )
                self.assertTrue(old.scalar_one().is_active)
                disabled = await asyncio.create_task(
                    self.client.patch(
                        f"/v1/admin/plans/{subscription['plan_id']}/active",
                        headers=self.headers,
                        json={"is_active": False},
                    ),
                    context=Context(),
                )
                self.assertEqual(disabled.status_code, 200)
                projection = await query.get(
                    subscription["id"], customer["id"]
                )
                self.assertFalse(projection.quote_available)
                self.assertFalse(projection.eligible)
                self.assertEqual(
                    projection.reason_code, "renewal_quote_unavailable"
                )
