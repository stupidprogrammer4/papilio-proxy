import asyncio
import os
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

TEST_URL = os.getenv("PAPILIO_TEST_DATABASE_URL")
PRIOR = "0056_ip_lease_transitions"
CURRENT = "0057_ip_session_precision"


@skipUnless(TEST_URL, "Requires isolated MySQL")
class IpSessionPrecisionMigrationTest(IsolatedAsyncioTestCase):
    async def test_populated_56_preserved_and_precision_downgrade_guarded(
        self,
    ):
        base = make_url(str(TEST_URL))
        schema = "papilio_ip_precision_migration_test_" + uuid4().hex[:12]
        assert base.host == "127.0.0.1" and "test" in schema
        target = base.set(database=schema)
        maintenance = create_async_engine(base, pool_size=1, max_overflow=0)
        engine = create_async_engine(target, pool_size=1, max_overflow=0)
        config = Config("alembic.ini")
        config.set_main_option(
            "sqlalchemy.url", target.render_as_string(hide_password=False)
        )

        async def migrate(operation, revision):
            with patch.dict(
                os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
            ):
                await asyncio.to_thread(operation, config, revision)

        async def read_state():
            async with engine.connect() as connection:
                rows = await connection.execute(
                    text(
                        "SELECT i.*,s.*,w.balance_rial,p.policy_json,l.iss"
                        "ued_until "
                        "FROM tbl_ip_sessions i JOIN tbl_subscriptions s "
                        "ON s.id=i.subscription_id JOIN tbl_wallets w "
                        "ON w.customer_id=s.customer_id JOIN tbl_purchased"
                        "_ip_policies p "
                        "ON p.subscription_id=s.id JOIN tbl_ip_lease_states l "
                        "ON l.subscription_id=s.id ORDER BY i.id"
                    )
                )
                return [tuple(row) for row in rows]

        async with maintenance.begin() as connection:
            await connection.execute(text(f"CREATE DATABASE `{schema}`"))
        try:
            await migrate(command.upgrade, PRIOR)
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO tbl_customers(id,display_name,is_active) "
                        "VALUES(1,'Synthetic precision buyer',1)"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO tbl_plans(id,code,title,quota_bytes,d"
                        "uration_days,"
                        "price_rial,sort_order,is_active) "
                        "VALUES(1,'precision','Synthetic plan',1000000,30,"
                        "100000,0,1)"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO tbl_subscriptions(id,customer_id,plan"
                        "_id,quota_bytes,"
                        "price_rial,duration_days,expires_at,status,auto_r"
                        "enew,renewal_count,"
                        "purchase_key) VALUES(1,1,1,1000000,100000,30,'203"
                        "0-01-01',"
                        "'active',0,0,'precision')"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO tbl_wallets(id,customer_id,balance_ri"
                        "al) VALUES(1,1,200000)"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO tbl_purchased_ip_policies(subscriptio"
                        "n_id,plan_id,"
                        "source,policy_json) VALUES(1,1,'plan_override','{}')"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO tbl_nodes(id,code,label,public_host,p"
                        "ublic_port,"
                        "protocol,agent_key_hash,is_enabled) VALUES(1,'pre"
                        "cision',"
                        "'Synthetic node','example.invalid',443,'vless_rea"
                        "lity',:hash,1)"
                    ),
                    {"hash": "0" * 64},
                )
                await connection.execute(
                    text(
                        "INSERT INTO tbl_ip_lease_states(subscription_id,h"
                        "istory_complete,"
                        "issued_until) VALUES(1,1,'2030-01-01 00:00:01.250"
                        "000')"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO tbl_ip_sessions(subscription_id,sourc"
                        "e_ip,last_node_id,"
                        "first_seen_at,last_seen_at,expires_at,blocked_unt"
                        "il) VALUES"
                        "(1,'192.0.2.170',1,'2029-12-31 23:59:59','2030-01"
                        "-01',"
                        "'2030-01-01 00:00:01',NULL),"
                        "(1,'192.0.2.171',1,'2029-12-31 23:59:59','2030-01"
                        "-01',"
                        "'2030-01-01','2030-01-01 00:00:02')"
                    )
                )
            before = await read_state()
            self.assertEqual(len(before), 2)
            await migrate(command.upgrade, CURRENT)
            self.assertEqual(await read_state(), before)
            async with engine.connect() as connection:
                precision = await connection.execute(
                    text(
                        "SELECT COLUMN_NAME,DATETIME_PRECISION FROM INFORM"
                        "ATION_SCHEMA.COLUMNS "
                        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tbl"
                        "_ip_sessions' "
                        "AND COLUMN_NAME IN ('first_seen_at','last_seen_at"
                        "','expires_at',"
                        "'blocked_until') ORDER BY COLUMN_NAME"
                    )
                )
                self.assertEqual(
                    list(precision),
                    [
                        ("blocked_until", 6),
                        ("expires_at", 6),
                        ("first_seen_at", 6),
                        ("last_seen_at", 6),
                    ],
                )
            with self.assertRaisesRegex(RuntimeError, "exact IP lease"):
                await migrate(command.downgrade, PRIOR)
            self.assertEqual(await read_state(), before)
            async with engine.connect() as connection:
                version = await connection.execute(
                    text("SELECT version_num FROM alembic_version")
                )
                self.assertEqual(version.scalar_one(), CURRENT)
            async with engine.begin() as connection:
                await connection.execute(text("DELETE FROM tbl_ip_sessions"))
            await migrate(command.downgrade, PRIOR)
            await migrate(command.upgrade, CURRENT)
        finally:
            await engine.dispose()
            async with maintenance.begin() as connection:
                await connection.execute(text(f"DROP DATABASE `{schema}`"))
            await maintenance.dispose()
