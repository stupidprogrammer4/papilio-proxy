import asyncio
import os
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
from sqlalchemy import select
from sqlmodel import col

from src.config.providers import infrastructure_providers
from src.config.settings import PapilioSettings
from src.modules.accounts.staff.app.passwords import Passwords
from src.modules.accounts.staff.app.services import StaffAuth
from src.modules.accounts.staff.infra.mysql import StaffRepository
from src.modules.accounts.staff.infra.readers import StaffSessionReader
from src.modules.billing.wallet.infra.tables import WalletEntryTable

TEST_URL = os.getenv("PAPILIO_TEST_DATABASE_URL")


@skipUnless(TEST_URL, "Requires an isolated PAPILIO_TEST_DATABASE_URL")
class WalletWorkflowTest(IsolatedAsyncioTestCase):
    async def test_manual_approval_is_atomic_and_replay_safe(self) -> None:
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
        reference = "bank_" + uuid4().hex[:16]
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
                    origin = {"Origin": settings.public.admin_origin}
                    login = await client.post(
                        "/v1/admin/auth/login",
                        headers=origin,
                        json={
                            "username": username,
                            "password": "local-only-password-123",
                        },
                    )
                    self.assertEqual(login.status_code, 200)
                    headers = {
                        **origin,
                        "X-CSRF-Token": login.json()["csrf_token"],
                    }
                    customer = await client.post(
                        "/v1/admin/customers",
                        headers=headers,
                        json={"display_name": "مشتری آزمایشی"},
                    )
                    self.assertEqual(customer.status_code, 200)
                    customer_id = customer.json()["data"]["id"]
                    topup = await client.post(
                        "/v1/admin/payments/topups",
                        headers=headers,
                        json={
                            "customer_id": customer_id,
                            "amount_rial": 900_000,
                        },
                    )
                    self.assertEqual(topup.status_code, 200)
                    topup_id = topup.json()["data"]["id"]
                    path = f"/v1/admin/payments/topups/{topup_id}/approve"
                    approved = await client.post(
                        path,
                        headers=headers,
                        json={"bank_reference": reference},
                    )
                    self.assertEqual(approved.status_code, 200)
                    repeated = await client.post(
                        path,
                        headers=headers,
                        json={"bank_reference": reference},
                    )
                    self.assertEqual(repeated.status_code, 200)
                    balance = await client.get(
                        f"/v1/admin/payments/wallets/{customer_id}"
                    )
                    self.assertEqual(
                        balance.json()["data"]["balance_rial"], 900_000
                    )
                async with connection.uow() as independent:
                    result = await independent.execute(
                        select(WalletEntryTable).where(
                            col(WalletEntryTable.reference)
                            == f"topup:{topup_id}"
                        )
                    )
                    self.assertEqual(len(result.scalars().all()), 1)
            finally:
                await app.state.dishka_container.close()
        finally:
            await connection.dispose()
