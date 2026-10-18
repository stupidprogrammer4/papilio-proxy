import asyncio
import os
from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

import httpx
import yaml
from alembic import command
from alembic.config import Config
from papilio.api.application import create_app
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import select, update
from sqlmodel import col

from src.config.providers import infrastructure_providers
from src.config.settings import PapilioSettings
from src.modules.accounts.staff.app.passwords import Passwords
from src.modules.accounts.staff.app.services import StaffAuth
from src.modules.accounts.staff.infra.mysql import StaffRepository
from src.modules.accounts.staff.infra.readers import StaffSessionReader
from src.modules.billing.wallet.infra.mysql import WalletRepository
from src.modules.billing.wallet.infra.tables import WalletEntryTable
from src.modules.sales.subscriptions.domain.dtos import ProvisionFailure
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable
from src.modules.sales.subscriptions.interfaces import ISubscriptionCommand

TEST_URL = os.getenv("PAPILIO_TEST_DATABASE_URL")


@skipUnless(TEST_URL, "Requires an isolated PAPILIO_TEST_DATABASE_URL")
class RenewalWorkflowTest(IsolatedAsyncioTestCase):
    async def test_wallet_debit_and_replayed_due_renewal(self) -> None:
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", str(TEST_URL))
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(command.upgrade, config, "head")
        with open("config.yml.sample", encoding="utf-8") as source:
            raw = yaml.safe_load(source)
        raw["rate_limit"]["enabled"] = False
        raw["db"]["dsn"] = TEST_URL
        raw["db"]["test_dsn"] = TEST_URL
        settings = PapilioSettings.model_validate(raw)
        assert settings.db is not None
        connection = DBConnection(
            dsn=settings.db.dsn,
            pool_size=2,
            max_overflow=0,
            pool_timeout=30,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )
        username = "owner_" + uuid4().hex[:12]
        code = "renew_" + uuid4().hex[:12]
        try:
            async with connection.uow() as unit:
                auth = StaffAuth(
                    StaffRepository(unit),
                    Passwords(settings),
                    settings,
                    StaffSessionReader(unit),
                )
                await auth.create_owner(username, "local-only-password-123")
            app = create_app(
                settings,
                providers=infrastructure_providers(settings),
                middleware=(),
                docs_url=None,
            )
            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="https://admin.example.com",
                ) as client:
                    login = await client.post(
                        "/v1/admin/auth/login",
                        headers={"Origin": settings.public.admin_origin},
                        json={
                            "username": username,
                            "password": "local-only-password-123",
                        },
                    )
                    self.assertEqual(login.status_code, 200)
                    headers = {
                        "Origin": settings.public.admin_origin,
                        "X-CSRF-Token": login.json()["csrf_token"],
                    }
                    customer = await client.post(
                        "/v1/admin/customers",
                        headers=headers,
                        json={"display_name": "تمدید آزمایشی"},
                    )
                    self.assertEqual(customer.status_code, 200)
                    customer_id = customer.json()["data"]["id"]
                    plan = await client.post(
                        "/v1/admin/plans",
                        headers=headers,
                        json={
                            "code": code,
                            "title": "پلن تمدید",
                            "quota_bytes": 1_073_741_824,
                            "duration_days": 30,
                            "price_rial": 100_000,
                        },
                    )
                    self.assertEqual(plan.status_code, 200)
                    plan_id = plan.json()["data"]["id"]
                    active = await client.patch(
                        f"/v1/admin/plans/{plan_id}/active",
                        headers=headers,
                        json={"is_active": True},
                    )
                    self.assertEqual(active.status_code, 200)
                    topup = await client.post(
                        "/v1/admin/payments/topups",
                        headers=headers,
                        json={
                            "customer_id": customer_id,
                            "amount_rial": 250_000,
                        },
                    )
                    self.assertEqual(topup.status_code, 200)
                    topup_id = topup.json()["data"]["id"]
                    approved = await client.post(
                        f"/v1/admin/payments/topups/{topup_id}/approve",
                        headers=headers,
                        json={
                            "expected_revision": 1,
                            "bank_reference": "bank_" + uuid4().hex,
                        },
                    )
                    self.assertEqual(approved.status_code, 200)
                    purchase = await client.post(
                        "/v1/admin/subscriptions",
                        headers=headers,
                        json={
                            "customer_id": customer_id,
                            "plan_id": plan_id,
                            "auto_renew": True,
                            "purchase_key": "admin:" + uuid4().hex,
                        },
                    )
                    self.assertEqual(purchase.status_code, 200)
                    self.assertEqual(
                        purchase.json()["data"]["status"], "pending_provision"
                    )
                    subscription_id = purchase.json()["data"]["id"]
                    balance = await client.get(
                        f"/v1/admin/payments/wallets/{customer_id}"
                    )
                    self.assertEqual(
                        balance.json()["data"]["balance_rial"], 150_000
                    )
                async with connection.uow() as unit:
                    await unit.execute(
                        update(SubscriptionTable)
                        .where(col(SubscriptionTable.id) == subscription_id)
                        .values(
                            status="active",
                            expires_at=datetime.now(UTC).replace(tzinfo=None)
                            - timedelta(minutes=1),
                        )
                    )
                    await unit.commit()
                async with app.state.dishka_container() as scope:
                    renewal = await scope.get(ISubscriptionCommand)
                    first = await renewal.renew_due(subscription_id)
                    self.assertEqual(first.renewal_count, 1)
                    self.assertEqual(first.status, "pending_provision")
                async with app.state.dishka_container() as scope:
                    renewal = await scope.get(ISubscriptionCommand)
                    repeated = await renewal.renew_due(subscription_id)
                    self.assertEqual(repeated.renewal_count, 1)
                async with connection.uow() as independent:
                    entries = await independent.execute(
                        select(WalletEntryTable).where(
                            col(WalletEntryTable.reference)
                            == f"renewal:{subscription_id}:1"
                        )
                    )
                    self.assertEqual(len(entries.scalars().all()), 1)
                    wallet = await WalletRepository(independent).by_customer(
                        customer_id
                    )
                    self.assertIsNotNone(wallet)
                    assert wallet is not None
                    self.assertEqual(wallet.balance_rial, 50_000)
                async with app.state.dishka_container() as scope:
                    recovery = await scope.get(ISubscriptionCommand)
                    failed = await recovery.fail_provision(
                        subscription_id,
                        ProvisionFailure(reason="Node rejected provisioning"),
                        1,
                    )
                    self.assertEqual(failed.status, "failed")
                async with app.state.dishka_container() as scope:
                    recovery = await scope.get(ISubscriptionCommand)
                    repeated_failure = await recovery.fail_provision(
                        subscription_id,
                        ProvisionFailure(reason="Node rejected provisioning"),
                        1,
                    )
                    self.assertEqual(repeated_failure.status, "failed")
                async with connection.uow() as independent:
                    wallet = await WalletRepository(independent).by_customer(
                        customer_id
                    )
                    assert wallet is not None
                    self.assertEqual(wallet.balance_rial, 150_000)
                    refund = await independent.execute(
                        select(WalletEntryTable).where(
                            col(WalletEntryTable.reference)
                            == f"provision_refund:{subscription_id}:1"
                        )
                    )
                    self.assertEqual(len(refund.scalars().all()), 1)
            finally:
                await app.state.dishka_container.close()
        finally:
            await connection.dispose()
