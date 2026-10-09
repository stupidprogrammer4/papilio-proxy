import asyncio
import hashlib
import hmac
import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

import httpx
import yaml
from alembic import command
from alembic.config import Config
from papilio.api.application import create_app
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.transaction import transaction
from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import select, update
from sqlmodel import col

from src.config.providers import infrastructure_providers
from src.config.settings import PapilioSettings
from src.modules.accounts.staff.app.passwords import Passwords
from src.modules.accounts.staff.app.services import StaffAuth
from src.modules.accounts.staff.domain.models import StaffModel
from src.modules.accounts.staff.infra.mysql import StaffRepository
from src.modules.accounts.staff.infra.readers import StaffSessionReader
from src.modules.billing.reviews.infra.tables import PaymentReviewTable
from src.modules.billing.wallet.infra.tables import (
    TopupTable,
    WalletEntryTable,
)
from src.modules.network.health.infra.tables import NodeHealthTable
from src.modules.network.nodes.infra.tables import ProbeTable
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable

TEST_URL = os.getenv("PAPILIO_TEST_DATABASE_URL")
REDIS_URL = os.getenv("PAPILIO_TEST_REDIS_URL")


@skipUnless(TEST_URL and REDIS_URL, "Requires isolated MySQL and Redis")
class AutomationWorkflowFixture(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        migration = Config("alembic.ini")
        migration.set_main_option("sqlalchemy.url", str(TEST_URL))
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(command.upgrade, migration, "head")
        self.raw = yaml.safe_load(Path("config.yml.sample").read_text())
        self.raw["db"]["dsn"] = TEST_URL
        self.raw["redis"]["url"] = REDIS_URL
        self.raw["tasks"]["scheduler"].update(
            url=REDIS_URL,
            schedule_prefix="papilio:test:schedules:" + uuid4().hex,
        )
        self.raw["rate_limit"]["enabled"] = False
        self.settings = PapilioSettings.model_validate(self.raw)
        assert self.settings.db is not None
        db = self.settings.db
        self.connection = DBConnection(
            dsn=db.dsn,
            pool_size=db.pool_size,
            max_overflow=db.max_overflow,
            pool_timeout=db.pool_timeout,
            pool_recycle=db.pool_recycle,
            uow_factory=MySQLUnitOfWork,
        )
        self.suffix = uuid4().hex[:12]
        self.username = "ops_" + self.suffix
        self.password = "isolated-ops-password"
        async with self.connection.uow() as unit:
            await StaffAuth(
                StaffRepository(unit),
                Passwords(self.settings),
                self.settings,
                StaffSessionReader(unit),
            ).create_owner(self.username, self.password)
        self.app = create_app(
            self.settings,
            providers=infrastructure_providers(self.settings),
            middleware=(),
            docs_url=None,
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="https://admin.example.com",
        )
        login = await self.client.post(
            "/v1/admin/auth/login",
            headers={"Origin": self.settings.public.admin_origin},
            json={"username": self.username, "password": self.password},
        )
        self.assertEqual(login.status_code, 200)
        self.headers = {
            "Origin": self.settings.public.admin_origin,
            "X-CSRF-Token": login.json()["csrf_token"],
        }

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.app.state.dishka_container.close()
        await self.connection.dispose()

    async def post(self, path, data=None):
        response = await self.client.post(
            path, headers=self.headers, json=data
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    async def get(self, path):
        response = await self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return response.json()

    async def sms(self, amount, reference, sent_at=None):
        body = json.dumps(
            {
                "event_id": "ops_" + uuid4().hex,
                "sender": "bank-fixture",
                "message": f"واریز {amount} ریال پیگیری {reference}",
                "sent_at": (sent_at or datetime.now(UTC)).isoformat(),
            }
        ).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(
            self.settings.security.sms_webhook_key.encode(),
            timestamp.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        response = await self.client.post(
            "/v1/webhooks/sms",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Papilio-Timestamp": timestamp,
                "X-Papilio-Signature": signature,
            },
        )
        self.assertEqual(response.status_code, 200)

    async def paid_subscription(self, auto_renew=False):
        customer = await self.post(
            "/v1/admin/customers",
            {"display_name": "آزمون اتوماسیون " + self.suffix},
        )
        plan = await self.post(
            "/v1/admin/plans",
            {
                "code": "ops_" + self.suffix,
                "title": "پلن آزمون",
                "quota_bytes": 1000000000,
                "duration_days": 30,
                "price_rial": 100000,
            },
        )
        active = await self.client.patch(
            f"/v1/admin/plans/{plan['id']}/active",
            headers=self.headers,
            json={"is_active": True},
        )
        self.assertEqual(active.status_code, 200)
        topup = await self.post(
            "/v1/admin/payments/topups",
            {"customer_id": customer["id"], "amount_rial": 300000},
        )
        await self.post(
            f"/v1/admin/payments/topups/{topup['id']}/approve",
            {"bank_reference": "seed_" + self.suffix},
        )
        subscription = await self.post(
            "/v1/admin/subscriptions",
            {
                "customer_id": customer["id"],
                "plan_id": plan["id"],
                "purchase_key": "ops_" + self.suffix,
                "auto_renew": auto_renew,
            },
        )
        return customer, subscription


class AutomationWorkflowTest(AutomationWorkflowFixture):
    async def test_payment_matches_stale_review_and_settlement_boundaries(
        self,
    ):
        customer = await self.post(
            "/v1/admin/customers", {"display_name": "بررسی " + self.suffix}
        )
        topup = await self.post(
            "/v1/admin/payments/topups",
            {"customer_id": customer["id"], "amount_rial": 123456},
        )
        path = f"/v1/admin/payments/reviews/{topup['id']}/check"
        self.assertEqual((await self.post(path))["status"], "waiting")
        reference = str(int(self.suffix, 16))
        await self.sms(
            123456, reference, datetime.now(UTC) + timedelta(days=1)
        )
        self.assertEqual((await self.post(path))["status"], "waiting")
        await self.sms(123456, reference)
        await self.sms(123456, reference)
        self.assertEqual((await self.post(path))["status"], "candidate")
        review = await self.get(
            f"/v1/admin/payments/reviews?customer_id={customer['id']}&per_page=1"
        )
        self.assertEqual(review["data"][0]["candidate_count"], 1)
        self.assertEqual(
            (await self.get(f"/v1/admin/payments/wallets/{customer['id']}"))[
                "data"
            ]["balance_rial"],
            0,
        )
        competing = await self.post(
            "/v1/admin/payments/topups",
            {"customer_id": customer["id"], "amount_rial": 123456},
        )
        self.assertEqual((await self.post(path))["status"], "ambiguous")
        await self.post(
            f"/v1/admin/payments/topups/{competing['id']}/approve",
            {"bank_reference": reference},
        )
        self.assertEqual((await self.post(path))["status"], "waiting")
        self.assertEqual(
            (
                await self.post(
                    f"/v1/admin/payments/reviews/{competing['id']}/check"
                )
            )["status"],
            "closed",
        )
        async with self.connection.uow() as unit:
            async with transaction():
                await unit.execute(
                    update(TopupTable)
                    .where(col(TopupTable.id) == topup["id"])
                    .values(
                        created_at=datetime.now(UTC).replace(tzinfo=None)
                        - timedelta(hours=72)
                    )
                )
        self.assertEqual((await self.post(path))["status"], "stale")
        async with self.connection.uow() as independent:
            payment = await independent.execute(
                select(TopupTable).where(col(TopupTable.id) == topup["id"])
            )
            self.assertEqual(payment.scalar_one().status, "pending")
            count = await independent.execute(
                select(PaymentReviewTable).where(
                    col(PaymentReviewTable.topup_id) == topup["id"]
                )
            )
            self.assertEqual(len(count.scalars().all()), 1)
        await self.post(
            f"/v1/admin/payments/topups/{topup['id']}/approve",
            {"bank_reference": "late_" + self.suffix},
        )
        self.assertEqual((await self.post(path))["status"], "closed")
        history = await self.get(
            f"/v1/admin/payments/wallets/{customer['id']}/entries?per_page=1"
        )
        second = await self.get(
            f"/v1/admin/payments/wallets/{customer['id']}/entries?per_page=1&page=2"
        )
        self.assertEqual(history["meta"]["pager"]["total_items"], 2)
        self.assertNotEqual(history["data"][0]["id"], second["data"][0]["id"])
        self.assertEqual(
            sum(
                row["amount_rial"] for row in history["data"] + second["data"]
            ),
            246912,
        )

    async def test_node_health_uses_fresh_authorized_samples(self):
        registered = await self.post(
            "/v1/admin/network/nodes",
            {
                "code": "ops_" + self.suffix,
                "label": "نود آزمون",
                "public_host": "example.invalid",
                "public_port": 443,
                "protocol": "vless_reality",
            },
        )
        node = registered["node"]
        path = f"/v1/admin/network/health/{node['id']}/check"
        self.assertEqual((await self.post(path))["status"], "disabled")
        enabled = await self.client.patch(
            f"/v1/admin/network/nodes/{node['id']}/enabled",
            headers=self.headers,
            json={"enabled": True},
        )
        self.assertEqual(enabled.status_code, 200)
        self.assertEqual((await self.post(path))["status"], "unknown")

        async def report(index):
            response = await self.client.post(
                f"/v1/nodes/{node['code']}/probes",
                headers={"X-Papilio-Node-Key": registered["agent_key"]},
                json={
                    "event_id": f"{self.suffix}_{index}",
                    "client_network": "test-network",
                    "success": True,
                    "latency_ms": 20 + index,
                    "sampled_at": datetime.now(UTC).isoformat(),
                },
            )
            self.assertEqual(response.status_code, 200)

        await asyncio.gather(*(report(index) for index in range(3)))
        self.assertEqual((await self.post(path))["status"], "healthy")
        fresh = await self.get(
            f"/v1/admin/network/health?node_id={node['id']}"
        )
        self.assertEqual(fresh["data"][0]["average_latency_ms"], 21)
        async with self.connection.uow() as unit:
            async with transaction():
                await unit.execute(
                    update(ProbeTable)
                    .where(col(ProbeTable.node_id) == node["id"])
                    .values(
                        sampled_at=datetime.now(UTC).replace(tzinfo=None)
                        - timedelta(hours=2)
                    )
                )
        self.assertEqual((await self.post(path))["status"], "stale")
        async with self.connection.uow() as independent:
            result = await independent.execute(
                select(NodeHealthTable).where(
                    col(NodeHealthTable.node_id) == node["id"]
                )
            )
            self.assertEqual(result.scalar_one().sample_count, 0)

    async def test_subscription_attention_and_ledger_preserve_paid_order(self):
        customer, subscription = await self.paid_subscription(auto_renew=True)
        path = f"/v1/admin/subscriptions/attention/{subscription['id']}/check"
        self.assertEqual((await self.post(path))["status"], "clear")
        async with self.connection.uow() as unit:
            async with transaction():
                await unit.execute(
                    update(SubscriptionTable)
                    .where(col(SubscriptionTable.id) == subscription["id"])
                    .values(
                        created_at=datetime.now(UTC).replace(tzinfo=None)
                        - timedelta(hours=1)
                    )
                )
        self.assertEqual(
            (await self.post(path))["status"], "provisioning_delayed"
        )
        restored = await self.get(
            f"/v1/admin/subscriptions/{subscription['id']}"
        )
        self.assertEqual(restored["data"]["status"], "pending_provision")
        self.assertEqual(
            datetime.fromisoformat(restored["data"]["expires_at"]).utcoffset(),
            timedelta(0),
        )
        await self.post(
            f"/v1/admin/subscriptions/{subscription['id']}/provision-failed",
            {"reason": "خطای کنترل‌شده در راه‌اندازی"},
        )
        await self.post(
            f"/v1/admin/subscriptions/{subscription['id']}/provision-failed",
            {"reason": "تلاش مجدد برای همان خطا"},
        )
        self.assertEqual(
            (await self.post(path))["status"], "provisioning_failed"
        )
        refunds = await self.get(
            f"/v1/admin/payments/wallets/{customer['id']}/entries?reason=provision_refund"
        )
        self.assertEqual(len(refunds["data"]), 1)
        self.assertEqual(refunds["data"][0]["balance_after_rial"], 300000)
        async with self.connection.uow() as independent:
            result = await independent.execute(
                select(WalletEntryTable).where(
                    col(WalletEntryTable.reference)
                    == f"provision_refund:{subscription['id']}:0"
                )
            )
            self.assertEqual(len(result.scalars().all()), 1)

    async def test_read_only_staff_can_observe_but_cannot_run_checks(self):
        customer = await self.post(
            "/v1/admin/customers", {"display_name": "مجوز " + self.suffix}
        )
        topup = await self.post(
            "/v1/admin/payments/topups",
            {"customer_id": customer["id"], "amount_rial": 99991},
        )
        hashed = await Passwords(self.settings).hash(self.password)
        readonly = "reader_" + self.suffix
        async with self.connection.uow() as unit:
            async with transaction():
                repo = StaffRepository(unit)
                staff = await repo.create(
                    StaffModel(
                        username=readonly, password_hash=hashed, is_active=True
                    )
                )
                await repo.add_grant(staff.id, "payments:read")
        login = await self.client.post(
            "/v1/admin/auth/login",
            headers={"Origin": self.settings.public.admin_origin},
            json={"username": readonly, "password": self.password},
        )
        self.assertEqual(login.status_code, 200)
        headers = {
            "Origin": self.settings.public.admin_origin,
            "X-CSRF-Token": login.json()["csrf_token"],
        }
        self.assertEqual(
            (
                await self.client.post(
                    f"/v1/admin/payments/reviews/{topup['id']}/check",
                    headers=headers,
                )
            ).status_code,
            403,
        )
        self.assertEqual(
            (await self.client.get("/v1/admin/network/health")).status_code,
            403,
        )
        self.assertEqual(
            (await self.client.get("/v1/admin/payments/reviews")).status_code,
            200,
        )
        schedules = await self.get("/v1/admin/automation/schedules")
        self.assertEqual(
            [row["key"] for row in schedules["data"]], ["payments"]
        )

    async def test_expiry_warning_and_insufficient_renewal_balance(self):
        customer, subscription = await self.paid_subscription(auto_renew=True)
        async with self.connection.uow() as unit:
            async with transaction():
                await unit.execute(
                    update(SubscriptionTable)
                    .where(col(SubscriptionTable.id) == subscription["id"])
                    .values(
                        status="active",
                        expires_at=datetime.now(UTC).replace(tzinfo=None)
                        + timedelta(hours=1),
                    )
                )
        path = f"/v1/admin/subscriptions/attention/{subscription['id']}/check"
        self.assertEqual((await self.post(path))["status"], "expiry_soon")
        await asyncio.gather(
            *(
                self.post(
                    "/v1/admin/subscriptions",
                    {
                        "customer_id": customer["id"],
                        "plan_id": subscription["plan_id"],
                        "purchase_key": f"{self.suffix}_extra_{index}",
                    },
                )
                for index in range(2)
            )
        )
        self.assertEqual((await self.post(path))["status"], "renewal_unfunded")
        balance = await self.get(
            f"/v1/admin/payments/wallets/{customer['id']}"
        )
        self.assertEqual(balance["data"]["balance_rial"], 0)
        attention = await self.get(
            f"/v1/admin/subscriptions/attention?customer_id={customer['id']}"
        )
        self.assertEqual(
            attention["data"][0]["subscription_id"], subscription["id"]
        )
        self.assertEqual(attention["data"][0]["wallet_balance_rial"], 0)

    async def test_native_scheduler_queue_worker_commits_checks_and_renewal(
        self,
    ):
        from tests.scheduler_runtime import exercise_native_schedulers

        customer, subscription = await self.paid_subscription(auto_renew=True)
        checkout = (await self.get("/v1/admin/settings"))["data"]["values"][
            "checkout"
        ]
        minimum = checkout["minimum_topup_rial"]
        maximum = checkout["maximum_topup_rial"]
        amount = minimum + int(self.suffix, 16) % (maximum - minimum + 1)
        topup = await self.post(
            "/v1/admin/payments/topups",
            {"customer_id": customer["id"], "amount_rial": amount},
        )
        await self.sms(amount, str(int(self.suffix, 16)))
        registered = await self.post(
            "/v1/admin/network/nodes",
            {
                "code": "queue_" + self.suffix,
                "label": "نود صف آزمون",
                "public_host": "example.invalid",
                "public_port": 443,
                "protocol": "vless_reality",
            },
        )
        node = registered["node"]
        enabled = await self.client.patch(
            f"/v1/admin/network/nodes/{node['id']}/enabled",
            headers=self.headers,
            json={"enabled": True},
        )
        self.assertEqual(enabled.status_code, 200)

        async def report(index):
            response = await self.client.post(
                f"/v1/nodes/{node['code']}/probes",
                headers={"X-Papilio-Node-Key": registered["agent_key"]},
                json={
                    "event_id": f"{self.suffix}_queue_{index}",
                    "client_network": "queue-network",
                    "success": True,
                    "latency_ms": 30,
                    "sampled_at": datetime.now(UTC).isoformat(),
                },
            )
            self.assertEqual(response.status_code, 200)

        await asyncio.gather(*(report(index) for index in range(3)))
        async with self.connection.uow() as unit:
            async with transaction():
                await unit.execute(
                    update(SubscriptionTable)
                    .where(col(SubscriptionTable.id) == subscription["id"])
                    .values(
                        status="active",
                        expires_at=datetime.now(UTC).replace(tzinfo=None)
                        - timedelta(seconds=1),
                    )
                )
        seen = await asyncio.to_thread(
            exercise_native_schedulers,
            self.raw,
            topup["id"],
            node["id"],
            subscription["id"],
        )
        self.assertEqual(seen, ("candidate", "healthy", 1))
        subscription_after = await self.get(
            f"/v1/admin/subscriptions/{subscription['id']}"
        )
        self.assertEqual(
            subscription_after["data"]["status"], "pending_provision"
        )
        self.assertEqual(subscription_after["data"]["renewal_count"], 1)
        renewal = await self.get(
            f"/v1/admin/payments/wallets/{customer['id']}/entries?reason=auto_renewal"
        )
        self.assertEqual(renewal["meta"]["pager"]["total_items"], 1)
        self.assertEqual(renewal["data"][0]["balance_after_rial"], 100000)
        # The second worker execution has its own native request scope.
        from src.modules.sales.subscriptions.interfaces import (
            ISubscriptionCommand,
        )

        async with self.app.state.dishka_container() as scope:
            command = await scope.get(ISubscriptionCommand)
            repeated = await command.renew_due(subscription["id"])
            self.assertEqual(repeated.renewal_count, 1)
        async with self.connection.uow() as independent:
            stored = await independent.execute(
                select(PaymentReviewTable).where(
                    col(PaymentReviewTable.topup_id) == topup["id"]
                )
            )
            self.assertEqual(stored.scalar_one().status, "candidate")
