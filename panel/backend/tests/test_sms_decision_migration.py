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
PRIOR = "0059_managed_provision_claims"


@skipUnless(TEST_URL, "Requires isolated MySQL")
class SmsDecisionMigrationTest(IsolatedAsyncioTestCase):
    async def test_existing_decision_survives_and_history_becomes_appendable(
        self,
    ):
        schema = "papilio_sms_decision_migration_test_" + uuid4().hex[:12]
        base_url = make_url(str(TEST_URL))
        assert base_url.host == "127.0.0.1" and "test" in schema
        target_url = base_url.set(database=schema)
        maintenance = DBConnection(
            dsn=str(TEST_URL),
            pool_size=2,
            max_overflow=0,
            pool_timeout=30,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )
        target = DBConnection(
            dsn=target_url.render_as_string(hide_password=False),
            pool_size=2,
            max_overflow=0,
            pool_timeout=30,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )
        migration = Config("alembic.ini")
        migration.set_main_option(
            "sqlalchemy.url", target_url.render_as_string(hide_password=False)
        )
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
                        "INSERT INTO tbl_sms_events "
                        "(id,event_id,sender,text_digest,sent_at) VALUES "
                        "(1,'prior-decision-event','SYNTHETIC_BANK',"
                        "REPEAT('a',64),'2026-10-01 12:00:00')"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_sms_settlement_decisions "
                        "(sms_event_id,status,reason_code,checked_at,"
                        "candidate_count) VALUES "
                        "(1,'ambiguous','sms_topup_ambiguous',"
                        "'2026-10-01 12:01:00',2)"
                    )
                )
                await unit.commit()
            with patch.dict(
                os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
            ):
                await asyncio.to_thread(command.upgrade, migration, "head")
            async with target.uow() as unit:
                prior = (
                    await unit.execute(
                        text(
                            "SELECT status,reason_code,candidate_count "
                            "FROM tbl_sms_settlement_decisions "
                            "WHERE sms_event_id=1"
                        )
                    )
                ).one()
                self.assertEqual(
                    tuple(prior),
                    ("ambiguous", "sms_topup_ambiguous", 2),
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_sms_settlement_decisions "
                        "(sms_event_id,status,checked_at,candidate_count) "
                        "VALUES (1,'approved','2026-10-01 12:02:00',1)"
                    )
                )
                count = (
                    await unit.execute(
                        text(
                            "SELECT COUNT(*) FROM "
                            "tbl_sms_settlement_decisions "
                            "WHERE sms_event_id=1"
                        )
                    )
                ).scalar_one()
                self.assertEqual(count, 2)
        finally:
            await target.dispose()
            async with maintenance.uow() as unit:
                await unit.execute(text(f"DROP DATABASE `{schema}`"))
            await maintenance.dispose()
