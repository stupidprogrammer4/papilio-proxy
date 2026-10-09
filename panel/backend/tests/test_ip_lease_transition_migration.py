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
PRIOR = "0055_purchased_ip_policy"
CURRENT = "0056_ip_lease_transitions"


@skipUnless(TEST_URL, "Requires isolated MySQL")
class IpLeaseTransitionMigrationTest(IsolatedAsyncioTestCase):
    async def test_populated_55_preserved_unknown_history_and_downgrade_guard(
        self,
    ):
        schema = "papilio_ip_lease_migration_test_" + uuid4().hex[:12]
        base = make_url(str(TEST_URL))
        assert base.host == "127.0.0.1" and "test" in schema
        target_url = base.set(database=schema)

        def connection(dsn):
            return DBConnection(
                dsn=dsn,
                pool_size=2,
                max_overflow=0,
                pool_timeout=30,
                pool_recycle=1800,
                uow_factory=MySQLUnitOfWork,
            )

        maintenance = connection(str(TEST_URL))
        target = connection(target_url.render_as_string(hide_password=False))
        config = Config("alembic.ini")
        config.set_main_option(
            "sqlalchemy.url", target_url.render_as_string(hide_password=False)
        )

        async def migrate(operation, revision):
            with patch.dict(
                os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
            ):
                await asyncio.to_thread(operation, config, revision)

        async def read(statement):
            async with target.uow() as unit:
                result = await unit.execute(text(statement))
                return [tuple(row) for row in result.all()]

        async with maintenance.uow() as unit:
            await unit.execute(text(f"CREATE DATABASE `{schema}`"))
        try:
            await migrate(command.upgrade, PRIOR)
            async with target.uow() as unit:
                await unit.execute(
                    text(
                        (
                            "INSERT INTO tbl_customers(id,display_name,"
                            "is_active) "
                            "VALUES(1,'Synthetic migration buyer',1)"
                        )
                    )
                )
                await unit.execute(
                    text(
                        (
                            "INSERT INTO "
                            "tbl_plans(id,code,title,quota_bytes,duration_days,price_rial,sort_order,is_active)"
                            " VALUES(1,'migration','Synthetic "
                            "plan',1000000,30,100000,0,1)"
                        )
                    )
                )
                await unit.execute(
                    text(
                        (
                            "INSERT INTO "
                            "tbl_subscriptions(id,customer_id,plan_id,quota_bytes,price_rial,duration_days,expires_at,status,auto_renew,renewal_count,purchase_key)"
                            " "
                            "VALUES(1,1,1,1000000,100000,30,'2030-01-01','active',0,0,'migration')"
                        )
                    )
                )
                await unit.execute(
                    text(
                        (
                            "INSERT INTO tbl_wallets(id,customer_id,"
                            "balance_rial) "
                            "VALUES(1,1,200000)"
                        )
                    )
                )
                await unit.execute(
                    text(
                        (
                            "INSERT INTO "
                            "tbl_purchased_ip_policies(subscription_id,plan_id,source,policy_json)"
                            " VALUES(1,1,'plan_override',:policy)"
                        )
                    ),
                    {
                        "policy": (
                            '{"enabled": false, "max_ips": 1, '
                            '"lease_seconds": 120, '
                            '"ban_seconds": 30, "mode": "reject_new"}'
                        )
                    },
                )
                await unit.commit()
            before = await read(
                (
                    "SELECT s.*,w.balance_rial,p.policy_json FROM "
                    "tbl_subscriptions s JOIN tbl_wallets w ON "
                    "w.customer_id=s.customer_id JOIN "
                    "tbl_purchased_ip_policies "
                    "p ON p.subscription_id=s.id"
                )
            )
            await migrate(command.upgrade, CURRENT)
            self.assertEqual(
                await read("SELECT COUNT(*) FROM tbl_ip_lease_states"), [(0,)]
            )
            self.assertEqual(
                await read(
                    (
                        "SELECT s.*,w.balance_rial,p.policy_json FROM "
                        "tbl_subscriptions s JOIN tbl_wallets w ON "
                        "w.customer_id=s.customer_id JOIN "
                        "tbl_purchased_ip_policies "
                        "p ON p.subscription_id=s.id"
                    )
                ),
                before,
            )
            async with target.uow() as unit:
                await unit.execute(
                    text(
                        (
                            "INSERT INTO "
                            "tbl_ip_lease_states(subscription_id,history_complete,issued_until,drain_until,pending_policy_json,previous_source,transition_mode,blocked_reason)"
                            " VALUES(1,0,'2030-01-01 "
                            "00:00:00.123456',NULL,'{}','legacy_unrestricted','drain_leases','legacy_lease_history_unknown')"
                        )
                    )
                )
                await unit.commit()
            lease_before = await read("SELECT * FROM tbl_ip_lease_states")
            with self.assertRaisesRegex(RuntimeError, "issued IP leases"):
                await migrate(command.downgrade, PRIOR)
            self.assertEqual(
                await read("SELECT * FROM tbl_ip_lease_states"), lease_before
            )
            self.assertEqual(
                await read("SELECT version_num FROM alembic_version"),
                [(CURRENT,)],
            )
            async with target.uow() as unit:
                await unit.execute(text("DELETE FROM tbl_ip_lease_states"))
                await unit.commit()
            await migrate(command.downgrade, PRIOR)
            await migrate(command.upgrade, CURRENT)
            self.assertEqual(
                await read("SELECT COUNT(*) FROM tbl_ip_lease_states"), [(0,)]
            )
            self.assertEqual(
                await read(
                    (
                        "SELECT s.*,w.balance_rial,p.policy_json FROM "
                        "tbl_subscriptions s JOIN tbl_wallets w ON "
                        "w.customer_id=s.customer_id JOIN "
                        "tbl_purchased_ip_policies "
                        "p ON p.subscription_id=s.id"
                    )
                ),
                before,
            )
        finally:
            await target.dispose()
            async with maintenance.uow() as unit:
                await unit.execute(text(f"DROP DATABASE `{schema}`"))
            await maintenance.dispose()
