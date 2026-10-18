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
PRIOR = "0065_receipt_ocr_outbox"
CURRENT = "0066_topup_revisions"


@skipUnless(TEST_URL, "Requires isolated MySQL")
class TopupRevisionMigrationTest(IsolatedAsyncioTestCase):
    async def test_existing_topups_receive_initial_revision(self) -> None:
        schema = "papilio_topup_revision_migration_test_" + uuid4().hex[:12]
        base_url = make_url(str(TEST_URL))
        assert base_url.host == "127.0.0.1" and "test" in schema
        target_url = base_url.set(database=schema)
        target_dsn = target_url.render_as_string(hide_password=False)
        maintenance = DBConnection(
            dsn=str(TEST_URL),
            pool_size=2,
            max_overflow=0,
            pool_timeout=30,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )
        target = DBConnection(
            dsn=target_dsn,
            pool_size=2,
            max_overflow=0,
            pool_timeout=30,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )
        migration = Config("alembic.ini")
        migration.set_main_option("sqlalchemy.url", target_dsn)
        async with maintenance.uow() as unit:
            await unit.execute(text(f"CREATE DATABASE `{schema}`"))
        try:
            with patch.dict(
                os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
            ):
                await asyncio.to_thread(command.upgrade, migration, PRIOR)
            async with target.uow() as unit:
                await unit.execute(
                    text(
                        "INSERT INTO tbl_customers(id,display_name,is_active) "
                        "VALUES (1,'Revision migration fixture',1)"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_topups "
                        "(id,customer_id,amount_rial,status,bank_reference) "
                        "VALUES (1,1,720000,'approved',"
                        "'prior-revision-reference')"
                    )
                )
                await unit.commit()
            with patch.dict(
                os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
            ):
                await asyncio.to_thread(command.upgrade, migration, CURRENT)
            async with target.uow() as unit:
                row = (
                    await unit.execute(
                        text(
                            "SELECT amount_rial,status,bank_reference,"
                            "revision "
                            "FROM tbl_topups WHERE id=1"
                        )
                    )
                ).one()
                self.assertEqual(
                    tuple(row),
                    (720000, "approved", "prior-revision-reference", 1),
                )
        finally:
            await target.dispose()
            async with maintenance.uow() as unit:
                await unit.execute(text(f"DROP DATABASE `{schema}`"))
            await maintenance.dispose()
