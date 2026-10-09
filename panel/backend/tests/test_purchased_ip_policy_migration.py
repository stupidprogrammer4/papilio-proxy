"""Native populated 53→54→55 preservation without invented legacy terms."""

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

from src.modules.network.managed_runtime.app.authority import (
    ManagedRuntimeAuthority,
)

TEST_URL = os.getenv("PAPILIO_TEST_DATABASE_URL")
PRIOR = "0053_payment_amount_identifiers"
SKELETON = "0054_managed_runtime"
CURRENT = "0055_purchased_ip_policy"


@skipUnless(TEST_URL, "Requires isolated MySQL")
class PurchasedIpPolicyMigrationTest(IsolatedAsyncioTestCase):
    async def test_populated_53_chain_preserves_records_and_guards_receipts(
        self,
    ):
        schema = "papilio_purchased_ip_migration_test_" + uuid4().hex[:12]
        base = make_url(str(TEST_URL))
        assert base.host == "127.0.0.1" and "test" in schema
        target_url = base.set(database=schema)

        def connection(dsn: str) -> DBConnection:
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
        migration = Config("alembic.ini")
        migration.set_main_option(
            "sqlalchemy.url", target_url.render_as_string(hide_password=False)
        )

        async def migrate(operation, revision):
            with patch.dict(
                os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
            ):
                await asyncio.to_thread(operation, migration, revision)

        async def rows(table):
            async with target.uow() as fresh:
                result = await fresh.execute(
                    text(f"SELECT * FROM {table} ORDER BY id")
                )
                return [tuple(row) for row in result.all()]

        async with maintenance.uow() as unit:
            await unit.execute(text(f"CREATE DATABASE `{schema}`"))
        try:
            await migrate(command.upgrade, PRIOR)
            async with target.uow() as unit:
                await unit.execute(
                    text("""
                        INSERT INTO tbl_staff(id, username, password_hash,
                        is_active) VALUES(1, 'migration-owner',
                        'opaque-password-hash', 1)
                    """)
                )
                await unit.execute(
                    text("""
                        INSERT INTO tbl_customers(id, display_name, is_active)
                        VALUES(1, 'Synthetic migration customer', 1)
                    """)
                )
                await unit.execute(
                    text("""
                        INSERT INTO tbl_plans(id, code, title, quota_bytes,
                        duration_days, price_rial, sort_order, is_active)
                        VALUES(1, 'migration-plan', 'Synthetic plan', 1000000,
                        30, 100000, 0, 1)
                    """)
                )
                await unit.execute(
                    text("""
                        INSERT INTO tbl_subscriptions(id, customer_id, plan_id,
                        quota_bytes, price_rial, duration_days, expires_at,
                        status, auto_renew, renewal_count, purchase_key)
                        VALUES(1, 1, 1, 1000000, 100000, 30, '2030-01-01',
                        'active', 0, 0, 'migration-purchase')
                    """)
                )
                await unit.execute(
                    text("""
                        INSERT INTO tbl_wallets(id, customer_id, balance_rial)
                        VALUES(1, 1, 200000)
                    """)
                )
                await unit.execute(
                    text("""
                        INSERT INTO tbl_topups(id, customer_id, amount_rial,
                        status, bank_reference, request_key) VALUES(1, 1,
                        300000, 'approved', 'synthetic-migration-bank',
                        'migration-topup')
                    """)
                )
                await unit.execute(
                    text("""
                        INSERT INTO tbl_wallet_entries(wallet_id, amount_rial,
                        balance_after_rial, reference, reason) VALUES(1,
                        300000, 300000, 'migration-credit', 'approved_topup'),
                        (1, -100000, 200000, 'migration-purchase', 'purchase')
                    """)
                )
                await unit.execute(
                    text("""
                        INSERT INTO tbl_nodes(id, code, label, public_host,
                        public_port, protocol, agent_key_hash, is_enabled)
                        VALUES(1, 'migration-node', 'Synthetic node',
                        'example.invalid', 443, 'vless_reality', REPEAT('a',
                        64), 0)
                    """)
                )
                await unit.execute(
                    text("""
                        INSERT INTO tbl_cores(id, node_id, code, label, kind)
                        VALUES(1, 1, 'migration-core', 'Synthetic core',
                        'xray')
                    """)
                )
                await unit.execute(
                    text("""
                        INSERT INTO tbl_configurations(id, node_id, core_id,
                        label, protocol, encrypted_settings, listen_port,
                        port_network) VALUES(1, 1, 1,
                        'Synthetic configuration', 'vless_reality',
                        'opaque-settings', 443, 'tcp')
                    """)
                )
                await unit.execute(
                    text("""
                        INSERT INTO tbl_profiles(id, configuration_id,
                        subscription_id, encrypted_credentials) VALUES(1, 1, 1,
                        'opaque-existing-profile')
                    """)
                )
                await unit.execute(
                    text("""
                        INSERT INTO tbl_core_runtime_revisions(id, core_id,
                        mode, bundle_sha256, snapshot_sha256,
                        entitlement_sha256, artifact_count, encrypted_payload)
                        VALUES(1, 1, 'merged', REPEAT('a', 64), REPEAT('b',
                        64), REPEAT('c', 64), 1, 'opaque-existing-runtime')
                    """)
                )
                await unit.commit()
            preserved = (
                "tbl_staff",
                "tbl_customers",
                "tbl_plans",
                "tbl_subscriptions",
                "tbl_wallets",
                "tbl_wallet_entries",
                "tbl_topups",
                "tbl_nodes",
                "tbl_cores",
                "tbl_configurations",
                "tbl_profiles",
                "tbl_core_runtime_revisions",
            )
            before = await asyncio.gather(
                *(rows(table) for table in preserved)
            )
            await migrate(command.upgrade, SKELETON)
            self.assertFalse(
                ManagedRuntimeAuthority().readiness().paid_bootstrap_available
            )
            managed = (
                "tbl_managed_installations",
                "tbl_managed_epochs",
                "tbl_managed_windows",
                "tbl_managed_barriers",
                "tbl_managed_admissions",
            )
            managed_rows = await asyncio.gather(
                *(rows(table) for table in managed)
            )
            self.assertTrue(all(not records for records in managed_rows))
            await migrate(command.upgrade, CURRENT)
            current_rows = await asyncio.gather(
                *(rows(table) for table in preserved)
            )
            for table, expected, actual in zip(
                preserved, before, current_rows, strict=True
            ):
                self.assertEqual(actual, expected, table)
            self.assertEqual(await rows("tbl_purchased_ip_policies"), [])
            # Empty new storage may be rolled back without touching history.
            await migrate(command.downgrade, PRIOR)
            current_rows = await asyncio.gather(
                *(rows(table) for table in preserved)
            )
            for table, expected, actual in zip(
                preserved, before, current_rows, strict=True
            ):
                self.assertEqual(actual, expected, table)
            await migrate(command.upgrade, CURRENT)
            async with target.uow() as unit:
                await unit.execute(
                    text(
                        """INSERT INTO tbl_purchased_ip_policies
                        (subscription_id, plan_id, source, policy_json)
                        VALUES(1,1,'plan_override',:policy)"""
                    ),
                    {
                        "policy": (
                            '{"enabled":true,"max_ips":1,"lease_seconds":120,'
                            '"ban_seconds":300,"mode":"reject_new"}'
                        )
                    },
                )
                await unit.commit()
            with self.assertRaisesRegex(RuntimeError, "purchased IP policy"):
                await migrate(command.downgrade, SKELETON)
            self.assertEqual(len(await rows("tbl_purchased_ip_policies")), 1)
            async with target.uow() as unit:
                await unit.execute(
                    text("DELETE FROM tbl_purchased_ip_policies")
                )
                await unit.execute(
                    text(
                        """INSERT INTO tbl_managed_installations
                        (node_id, core_id, runtime_revision_id,
                        installation_sha256, encrypted_manifest)
                        VALUES(1,1,1,REPEAT('d',64),
                        'opaque-immutable-installation')"""
                    )
                )
                await unit.commit()
            await migrate(command.downgrade, SKELETON)
            with self.assertRaisesRegex(
                RuntimeError, "managed authority receipts"
            ):
                await migrate(command.downgrade, PRIOR)
            self.assertEqual(len(await rows("tbl_managed_installations")), 1)
            current_rows = await asyncio.gather(
                *(rows(table) for table in preserved)
            )
            for table, expected, actual in zip(
                preserved, before, current_rows, strict=True
            ):
                self.assertEqual(actual, expected, table)
        finally:
            await target.dispose()
            async with maintenance.uow() as unit:
                await unit.execute(text(f"DROP DATABASE IF EXISTS `{schema}`"))
            await maintenance.dispose()
