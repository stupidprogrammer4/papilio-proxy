import asyncio
import os
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import text
from sqlalchemy.engine import make_url

TEST_URL = os.getenv("PAPILIO_TEST_DATABASE_URL")


@skipUnless(TEST_URL, "Requires isolated MySQL")
class CustomerAccessMigrationTest(IsolatedAsyncioTestCase):
    async def test_prior_customer_identity_and_wallet_survive_upgrade(self):
        schema = "papilio_upgrade_test_customer_migration_" + uuid4().hex[:12]
        maintenance = DBConnection(
            dsn=str(TEST_URL),
            pool_size=2,
            max_overflow=0,
            pool_timeout=30,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )
        url = make_url(str(TEST_URL)).set(database=schema)
        target = DBConnection(
            dsn=url.render_as_string(hide_password=False),
            pool_size=2,
            max_overflow=0,
            pool_timeout=30,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )
        async with maintenance.uow() as unit:
            await unit.execute(text(f"CREATE DATABASE `{schema}`"))
        try:
            config = Config("alembic.ini")
            config.set_main_option(
                "sqlalchemy.url", url.render_as_string(hide_password=False)
            )
            with patch.dict(
                os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
            ):
                await asyncio.to_thread(
                    command.upgrade, config, "0024_subscription_suspension"
                )
            async with target.uow() as unit:
                await unit.execute(
                    text(
                        "INSERT INTO tbl_customers"
                        "(id,display_name,telegram_id,is_active) "
                        "VALUES (1,'مشتری قبلی',123456789,0)"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_wallets(id,customer_id,balance_rial) "
                        "VALUES(1,1,125000)"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_wallet_entries"
                        "(wallet_id,amount_rial,balance_after_rial,"
                        "reference,reason) "
                        "VALUES(1,125000,125000,'prior-settlement','topup')"
                    )
                )
                await unit.commit()
            with patch.dict(
                os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
            ):
                await asyncio.to_thread(command.upgrade, config, "head")
            async with target.uow() as unit:
                row = (
                    await unit.execute(
                        text(
                            "SELECT id,display_name,telegram_id,is_active,"
                            "services_enabled,renewals_enabled,"
                            "service_hold_pending,service_hold_revision "
                            "FROM tbl_customers WHERE id=1"
                        )
                    )
                ).one()
                self.assertEqual(
                    tuple(row), (1, "مشتری قبلی", 123456789, 0, 1, 1, 0, 0)
                )
                wallet = (
                    await unit.execute(
                        text(
                            "SELECT balance_rial FROM tbl_wallets "
                            "WHERE customer_id=1"
                        )
                    )
                ).scalar_one()
                self.assertEqual(wallet, 125000)
                ledger = (
                    await unit.execute(
                        text(
                            "SELECT amount_rial,balance_after_rial,reference "
                            "FROM tbl_wallet_entries"
                        )
                    )
                ).one()
                self.assertEqual(
                    tuple(ledger), (125000, 125000, "prior-settlement")
                )
                self.assertEqual(
                    (
                        await unit.execute(
                            text(
                                "SELECT COUNT(*) "
                                "FROM tbl_customer_access_changes"
                            )
                        )
                    ).scalar_one(),
                    0,
                )
        finally:
            await target.dispose()
            async with maintenance.uow() as unit:
                await unit.execute(text(f"DROP DATABASE `{schema}`"))
            await maintenance.dispose()
