"""Preserve an existing enrolled phone when adding status reporting."""

import asyncio
import os
from unittest import IsolatedAsyncioTestCase, skipUnless
from uuid import uuid4

from alembic import command
from alembic.config import Config
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import text
from sqlalchemy.engine import make_url

TEST_URL = os.getenv("PAPILIO_TEST_DATABASE_URL")


@skipUnless(TEST_URL, "Requires isolated MySQL")
class SmsDeviceStatusMigrationTest(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.schema = "papilio_sms_status_" + uuid4().hex[:12]
        self.maintenance = DBConnection(
            dsn=str(TEST_URL),
            pool_size=2,
            max_overflow=0,
            pool_timeout=30,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )
        async with self.maintenance.uow() as unit:
            await unit.execute(text(f"CREATE DATABASE `{self.schema}`"))
        self.url = make_url(str(TEST_URL)).set(database=self.schema)
        self.connection = DBConnection(
            dsn=self.url.render_as_string(hide_password=False),
            pool_size=2,
            max_overflow=0,
            pool_timeout=30,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )
        await asyncio.to_thread(self.upgrade, "0068_receipt_annotations")

    def upgrade(self, revision: str) -> None:
        config = Config("alembic.ini")
        config.set_main_option(
            "sqlalchemy.url", self.url.render_as_string(hide_password=False)
        )
        command.upgrade(config, revision)

    async def asyncTearDown(self) -> None:
        await self.connection.dispose()
        async with self.maintenance.uow() as unit:
            await unit.execute(text(f"DROP DATABASE `{self.schema}`"))
        await self.maintenance.dispose()

    async def test_old_device_survives_status_migration(self) -> None:
        async with self.connection.uow() as unit:
            await unit.execute(
                text(
                    "INSERT INTO tbl_sms_devices "
                    "(approval_mode,destination_id,label,encrypted_key,"
                    "senders_json,is_active,revision,expires_at) "
                    "VALUES ('manual',NULL,'Existing phone','ciphertext',"
                    "'[\"OwnedBank\"]',true,7,'2030-01-01 00:00:00')"
                )
            )
            await unit.commit()
        await asyncio.to_thread(self.upgrade, "head")
        async with self.connection.uow() as unit:
            row = (
                await unit.execute(
                    text(
                        "SELECT label,revision,status_received_at,"
                        "pending_event_count,permission_granted,"
                        "delivery_state,last_acknowledged_event_id,"
                        "last_error_code "
                        "FROM tbl_sms_devices"
                    )
                )
            ).one()
        self.assertEqual(row.label, "Existing phone")
        self.assertEqual(row.revision, 7)
        self.assertEqual(tuple(row[2:]), (None, None, None, None, None, None))
