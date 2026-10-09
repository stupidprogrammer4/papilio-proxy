import asyncio
import json

from sqlalchemy import text

from tests.test_fulfillment_workflow import FulfillmentWorkflowFixture
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowTest,
)


class LoyaltyWorkflowTest(
    StaffAdministrationWorkflowTest, FulfillmentWorkflowFixture
):
    async def configure(self, *, first=1000):
        initial = await self.post("/v1/admin/loyalty/initialize")
        tiers = (await self.get("/v1/admin/loyalty/tiers"))["data"]
        bronze = next(row for row in tiers if row["code"] == "bronze")
        response = await self.client.put(
            f"/v1/admin/loyalty/tiers/{bronze['id']}",
            headers=self.headers,
            json={
                **bronze,
                "expected_revision": bronze["revision"],
                "discount_bps": 2000,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        response = await self.client.put(
            "/v1/admin/loyalty/policy",
            headers=self.headers,
            json={
                "expected_revision": initial["revision"],
                "values": {
                    **initial["values"],
                    "first_purchase_discount_bps": first,
                },
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    async def test_native_quote_promotion_replay_and_reversible_refund(self):
        policy = await self.configure()
        subscription, request, nodes, purchase = await self.setup_sale(
            quota_bytes=100 * 1024**3,
            failure_action="refund_wallet",
            attempts=1,
        )
        customer_id = subscription["customer_id"]
        self.assertEqual(subscription["price_rial"], 90000)
        balance_path = f"/v1/admin/payments/wallets/{customer_id}"
        self.assertEqual(
            (await self.get(balance_path))["data"]["balance_rial"], 210000
        )
        status_path = f"/v1/admin/loyalty/customers/{customer_id}"
        status = (await self.get(status_path))["data"]
        self.assertEqual(status["tier"]["code"], "bronze")
        self.assertEqual(status["purchased_bytes"], 100 * 1024**3)
        self.assertEqual(status["purchase_count"], 1)
        quote = (
            await self.get(
                status_path + f"/plans/{subscription['plan_id']}/quote"
            )
        )["data"]
        self.assertEqual(quote["price_rial"], 80000)
        self.assertEqual(quote["first_purchase_discount_bps"], 0)
        replay = await self.post("/v1/admin/subscriptions", purchase)
        self.assertEqual(replay["id"], subscription["id"])
        self.assertEqual(
            (await self.get(balance_path))["data"]["balance_rial"], 210000
        )
        initialized = await self.post("/v1/admin/loyalty/initialize")
        self.assertEqual(initialized, policy)
        tiers = (await self.get("/v1/admin/loyalty/tiers"))["data"]
        self.assertEqual(
            next(row for row in tiers if row["code"] == "bronze")[
                "discount_bps"
            ],
            2000,
        )
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        tasks = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"]
        claims = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        await self.ack(tasks[0], *claims[0])
        await self.ack(
            tasks[1],
            *claims[1],
            outcome="failed",
            error_code="adapter_unavailable",
        )
        self.assertEqual(
            (await self.get(status_path))["data"]["tier"]["code"], "bronze"
        )
        revokes = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        await self.ack(tasks[0], *revokes[0], outcome="revoked")
        self.assertEqual(
            (await self.get(balance_path))["data"]["balance_rial"], 210000
        )
        await self.ack(tasks[1], *revokes[1], outcome="revoked")
        await self.ack(tasks[1], *revokes[1], outcome="revoked")
        self.assertEqual(
            (await self.get(balance_path))["data"]["balance_rial"], 300000
        )
        status = (await self.get(status_path))["data"]
        self.assertEqual(status["tier"]["code"], "normal")
        self.assertEqual(status["purchased_bytes"], 0)
        self.assertEqual(status["purchase_count"], 0)
        async with self.connection.uow() as unit:
            records = (
                await unit.execute(
                    text(
                        "SELECT volume_bytes, purchase_count, paid_rial "
                        "FROM tbl_purchase_volumes "
                        "WHERE subscription_id=:id ORDER BY id"
                    ),
                    {"id": subscription["id"]},
                )
            ).all()
            self.assertEqual(
                [tuple(row) for row in records],
                [(100 * 1024**3, 1, 90000), (-100 * 1024**3, -1, -90000)],
            )
            saved = (
                await unit.execute(
                    text(
                        "SELECT commerce_json FROM tbl_subscriptions "
                        "WHERE id=:id"
                    ),
                    {"id": subscription["id"]},
                )
            ).scalar_one()
            self.assertEqual(json.loads(saved)["price_rial"], 90000)

    async def test_native_same_customer_concurrent_discount_and_stale_price(
        self,
    ):
        await self.configure(first=0)
        subscription, _, _, purchase = await self.setup_sale(
            quota_bytes=1024**3
        )
        policy = (await self.get("/v1/admin/loyalty/policy"))["data"]
        changed = await self.client.put(
            "/v1/admin/loyalty/policy",
            headers=self.headers,
            json={
                "expected_revision": policy["revision"],
                "values": {
                    **policy["values"],
                    "first_purchase_discount_bps": 5000,
                },
            },
        )
        self.assertEqual(changed.status_code, 200)
        results = await asyncio.gather(
            *(
                self.client.post(
                    "/v1/admin/subscriptions",
                    headers=self.headers,
                    json={
                        **purchase,
                        "purchase_key": self.suffix + f"-race-{index}",
                        "expected_price_rial": 100000,
                    },
                )
                for index in (1, 2)
            )
        )
        self.assertEqual([row.status_code for row in results], [200, 200])
        status = (
            await self.get(
                f"/v1/admin/loyalty/customers/{subscription['customer_id']}"
            )
        )["data"]
        self.assertEqual(status["purchase_count"], 3)
        self.assertEqual(status["purchased_bytes"], 3 * 1024**3)
        rejected = await self.client.post(
            "/v1/admin/subscriptions",
            headers=self.headers,
            json={
                **purchase,
                "purchase_key": self.suffix + "-rejected",
                "expected_price_rial": 50000,
            },
        )
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(
            (
                await self.get(
                    f"/v1/admin/payments/wallets/{subscription['customer_id']}"
                )
            )["data"]["balance_rial"],
            0,
        )

    async def test_native_first_discount_is_single_under_concurrency(self):
        await self.configure()
        subscription, _, _, source_purchase = await self.setup_sale()
        customer = await self.post(
            "/v1/admin/customers", {"display_name": "Race buyer"}
        )
        topup = await self.post(
            "/v1/admin/payments/topups",
            {"customer_id": customer["id"], "amount_rial": 300000},
        )
        await self.post(
            f"/v1/admin/payments/topups/{topup['id']}/approve",
            {"bank_reference": self.suffix + "-first-race"},
        )
        body = {
            **source_purchase,
            "customer_id": customer["id"],
            "expected_price_rial": 90000,
        }
        responses = await asyncio.gather(
            *(
                self.client.post(
                    "/v1/admin/subscriptions",
                    headers=self.headers,
                    json={
                        **body,
                        "purchase_key": self.suffix + f"-first-{index}",
                    },
                )
                for index in (1, 2)
            )
        )
        self.assertEqual(
            sorted(row.status_code for row in responses), [200, 409]
        )
        self.assertEqual(
            (await self.get(f"/v1/admin/payments/wallets/{customer['id']}"))[
                "data"
            ]["balance_rial"],
            210000,
        )
        status = (
            await self.get(f"/v1/admin/loyalty/customers/{customer['id']}")
        )["data"]
        self.assertEqual(status["purchase_count"], 1)
        self.assertEqual(status["lifetime_purchase_count"], 1)
        denied = await self.client.post(
            "/v1/customer/subscriptions",
            json={
                "plan_id": subscription["plan_id"],
                "purchase_key": self.suffix + "-unauth",
                "auto_renew": False,
            },
        )
        self.assertEqual(denied.status_code, 401)

    async def test_native_unlimited_credit_and_renewal_without_first_discount(
        self,
    ):
        from datetime import UTC, datetime, timedelta

        from src.modules.sales.subscriptions.interfaces import (
            ISubscriptionCommand,
        )

        await self.configure()
        subscription, _, _, _ = await self.setup_sale(quota_bytes=None)
        status_path = (
            f"/v1/admin/loyalty/customers/{subscription['customer_id']}"
        )
        self.assertEqual(
            (await self.get(status_path))["data"]["purchased_bytes"],
            100 * 1024**3,
        )
        self.assertEqual(
            subscription["commerce"]["renewal_price_rial"], 100000
        )
        # No-node fixture; the actual renewal command owns the debit.
        async with self.connection.uow() as unit:
            await unit.execute(
                text(
                    "UPDATE tbl_subscriptions SET provisioning_managed=0, "
                    "status=:state, expires_at=:expired WHERE id=:id"
                ),
                {
                    "id": subscription["id"],
                    "state": "active",
                    "expired": datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(seconds=1),
                },
            )
            await unit.commit()
        async with self.app.state.dishka_container() as scope:
            command = await scope.get(ISubscriptionCommand)
            renewed = await command.renew_due(subscription["id"])
            self.assertEqual(renewed.price_rial, 100000)
            self.assertEqual(renewed.renewal_count, 1)
        async with self.app.state.dishka_container() as scope:
            command = await scope.get(ISubscriptionCommand)
            await command.renew_due(subscription["id"])
        status = (await self.get(status_path))["data"]
        self.assertEqual(status["purchased_bytes"], 200 * 1024**3)
        self.assertEqual(status["purchase_count"], 1)
        async with self.connection.uow() as unit:
            history = (
                await unit.execute(
                    text(
                        "SELECT generation, commerce_json "
                        "FROM tbl_purchase_volumes "
                        "WHERE subscription_id=:id ORDER BY generation"
                    ),
                    {"id": subscription["id"]},
                )
            ).all()
            self.assertEqual([row[0] for row in history], [0, 1])
            quotes = [json.loads(row[1]) for row in history]
            self.assertEqual(
                [quote["price_rial"] for quote in quotes], [90000, 100000]
            )
            self.assertEqual(
                [quote["first_purchase_discount_bps"] for quote in quotes],
                [1000, 0],
            )
        self.assertEqual(
            (
                await self.get(
                    f"/v1/admin/payments/wallets/{subscription['customer_id']}"
                )
            )["data"]["balance_rial"],
            110000,
        )

    async def test_native_loyalty_scopes_and_typed_policy_validation(self):
        policy = await self.configure()
        staff = await self.post(
            "/v1/admin/staff",
            {
                "username": "loyalty_" + self.suffix,
                "password": "staff888",
                "is_active": True,
                "scopes": ["catalog:read"],
            },
        )
        delegate, headers = await self.login_staff(
            staff["username"], "staff888"
        )
        try:
            self.assertEqual(
                (await delegate.get("/v1/admin/loyalty/tiers")).status_code,
                200,
            )
            self.assertEqual(
                (
                    await delegate.post(
                        "/v1/admin/loyalty/initialize", headers=headers
                    )
                ).status_code,
                403,
            )
            self.assertEqual(
                (
                    await delegate.put(
                        "/v1/admin/loyalty/policy",
                        headers=headers,
                        json={
                            "expected_revision": policy["revision"],
                            "values": policy["values"],
                        },
                    )
                ).status_code,
                403,
            )
            self.assertEqual(
                (
                    await delegate.get("/v1/admin/loyalty/customers/1")
                ).status_code,
                403,
            )
        finally:
            await delegate.aclose()
        invalid = await self.client.put(
            "/v1/admin/loyalty/policy",
            headers=self.headers,
            json={
                "expected_revision": policy["revision"],
                "values": {
                    **policy["values"],
                    "unlimited_plan_bytes": {"1": -1},
                },
            },
        )
        self.assertEqual(invalid.status_code, 422)
        stale = await self.client.put(
            "/v1/admin/loyalty/policy",
            headers=self.headers,
            json={
                "expected_revision": policy["revision"] - 1,
                "values": policy["values"],
            },
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(
            (await self.get("/v1/admin/loyalty/policy"))["data"], policy
        )

    async def test_populated_upgrade_and_snapshot_downgrade_guard(self):
        from unittest.mock import patch

        from alembic import command
        from alembic.config import Config

        subscription, _, _, _ = await self.setup_sale()
        assert self.settings.db is not None
        migration = Config("alembic.ini")
        migration.set_main_option("sqlalchemy.url", self.settings.db.dsn)
        # Remove new facts only in the owned old-schema fixture.
        async with self.connection.uow() as unit:
            await unit.execute(text("DELETE FROM tbl_purchase_volumes"))
            await unit.execute(
                text("UPDATE tbl_subscriptions SET commerce_json=NULL")
            )
            await unit.commit()
        with patch.dict("os.environ", {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(
                command.downgrade, migration, "0041_notification_lease_index"
            )
            async with self.connection.uow() as unit:
                before = (
                    (
                        await unit.execute(
                            text(
                                "SELECT * FROM tbl_subscriptions WHERE id=:id"
                            ),
                            {"id": subscription["id"]},
                        )
                    )
                    .mappings()
                    .one()
                )
                before = dict(before)
            await asyncio.to_thread(command.upgrade, migration, "head")
        async with self.connection.uow() as unit:
            after = (
                (
                    await unit.execute(
                        text("SELECT * FROM tbl_subscriptions WHERE id=:id"),
                        {"id": subscription["id"]},
                    )
                )
                .mappings()
                .one()
            )
            after = dict(after)
            self.assertIsNone(after.pop("commerce_json"))
            self.assertEqual(after, before)
            self.assertEqual(
                (
                    await unit.execute(
                        text("SELECT COUNT(*) FROM tbl_purchase_volumes")
                    )
                ).scalar_one(),
                0,
            )
            await unit.execute(
                text(
                    "UPDATE tbl_subscriptions SET commerce_json=:quote "
                    "WHERE id=:id"
                ),
                {
                    "quote": json.dumps(subscription["commerce"]),
                    "id": subscription["id"],
                },
            )
            await unit.commit()
        with patch.dict("os.environ", {"PAPILIO_CONFIG": "config.yml.sample"}):
            with self.assertRaisesRegex(RuntimeError, "commerce history"):
                await asyncio.to_thread(
                    command.downgrade, migration, "0043_balancer_policies"
                )
        async with self.connection.uow() as unit:
            self.assertEqual(
                (
                    await unit.execute(
                        text("SELECT version_num FROM alembic_version")
                    )
                ).scalar_one(),
                "0044_customer_loyalty",
            )
            snapshot = (
                await unit.execute(
                    text(
                        "SELECT commerce_json FROM tbl_subscriptions "
                        "WHERE id=:id"
                    ),
                    {"id": subscription["id"]},
                )
            ).scalar_one()
            self.assertEqual(
                json.loads(snapshot)["price_rial"], subscription["price_rial"]
            )

    async def test_disabled_policy_preserves_buy_and_refund_after_tightening(
        self,
    ):
        policy = await self.configure()
        subscription, request, nodes, _ = await self.setup_sale(
            quota_bytes=100 * 1024**3,
            failure_action="refund_wallet",
            attempts=1,
        )
        assert self.settings.loyalty is not None
        self.settings.loyalty.max_tiers = 1
        response = await self.client.put(
            "/v1/admin/loyalty/policy",
            headers=self.headers,
            json={
                "expected_revision": policy["revision"],
                "values": {**policy["values"], "enabled": False},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        quote = (
            await self.get(
                f"/v1/admin/loyalty/customers/{subscription['customer_id']}"
                f"/plans/{subscription['plan_id']}/quote"
            )
        )["data"]
        self.assertEqual(quote["price_rial"], 100000)
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        tasks = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"]
        claims = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        await self.ack(tasks[0], *claims[0])
        await self.ack(
            tasks[1],
            *claims[1],
            outcome="failed",
            error_code="adapter_unavailable",
        )
        revokes = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        await self.ack(tasks[0], *revokes[0], outcome="revoked")
        await self.ack(tasks[1], *revokes[1], outcome="revoked")
        await self.ack(tasks[1], *revokes[1], outcome="revoked")
        wallet = (
            await self.get(
                f"/v1/admin/payments/wallets/{subscription['customer_id']}"
            )
        )["data"]
        self.assertEqual(wallet["balance_rial"], 300000)
        async with self.connection.uow() as unit:
            self.assertEqual(
                (
                    await unit.execute(
                        text(
                            "SELECT SUM(volume_bytes), SUM(paid_rial) "
                            "FROM tbl_purchase_volumes "
                            "WHERE subscription_id=:id"
                        ),
                        {"id": subscription["id"]},
                    )
                ).one(),
                (0, 0),
            )
