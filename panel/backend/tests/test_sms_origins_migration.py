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
PRIOR = "0051_node_capabilities"
CURRENT = "0052_sms_origin_settlement"


@skipUnless(TEST_URL, "Requires isolated MySQL")
class SmsOriginsMigrationTest(IsolatedAsyncioTestCase):
    async def test_populated_prior_credit_survives_without_origin_retagging(
        self,
    ):
        schema = "papilio_sms_origin_migration_test_" + uuid4().hex[:12]
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
                        "INSERT INTO tbl_customers(id,display_name,is_active) "
                        "VALUES (1,'Synthetic prior customer',1)"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_payment_destinations "
                        "(id,title,kind,encrypted_details,is_active) "
                        "VALUES(1,'Synthetic receiving card','card',"
                        "'opaque-prior-destination',1)"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_sms_devices "
                        "(id,label,encrypted_key,senders_json,is_active,revision,"
                        "expires_at,approval_mode,destination_id) VALUES "
                        "(1,'Synthetic enrolled device','opaque-prior-key',"
                        "'[\"SYNTHETIC_BANK\"]',1,3,'2030-01-01','unique_sms',1)"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_sms_events "
                        "(id,device_id,event_id,sender,text_digest,amount_rial,"
                        "bank_reference,sent_at) VALUES "
                        "(1,1,'prior-origin-migration-sms','SYNTHETIC_BANK',"
                        "REPEAT('a',64),240000,'prior-bank-reference',"
                        "'2026-10-01 12:00:00')"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_topups "
                        "(id,customer_id,amount_rial,status,bank_reference,"
                        "approved_by_device_id,approved_by_sms_id,destination_id,"
                        "request_key,encrypted_instruction) VALUES "
                        "(1,1,240000,'approved','prior-bank-reference',1,1,1,"
                        "'prior-origin-migration-topup','opaque-prior-instruction')"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_wallets(id,customer_id,balance_rial) "
                        "VALUES(1,1,240000)"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_wallet_entries "
                        "(wallet_id,amount_rial,balance_after_rial,"
                        "reference,reason) "
                        "VALUES(1,240000,240000,'prior-origin-migration-credit','topup')"
                    )
                )
                await unit.commit()
            with patch.dict(
                os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
            ):
                await asyncio.to_thread(command.upgrade, migration, CURRENT)
            async with target.uow() as unit:
                device = (
                    await unit.execute(
                        text(
                            "SELECT revision,approval_mode,encrypted_key,"
                            "parser_profile_id,settlement_identity_mode "
                            "FROM tbl_sms_devices WHERE id=1"
                        )
                    )
                ).one()
                self.assertEqual(
                    tuple(device),
                    (
                        3,
                        "unique_sms",
                        "opaque-prior-key",
                        None,
                        "bank_reference_required",
                    ),
                )
                topup = (
                    await unit.execute(
                        text(
                            "SELECT status,bank_reference,amount_rial,"
                            "approved_by_device_id,approved_by_sms_id,"
                            "encrypted_instruction,receiving_realm_id,"
                            "receiving_alias_id,captured_destination_revision "
                            "FROM tbl_topups WHERE id=1"
                        )
                    )
                ).one()
                self.assertEqual(
                    tuple(topup),
                    (
                        "approved",
                        "prior-bank-reference",
                        240000,
                        1,
                        1,
                        "opaque-prior-instruction",
                        None,
                        None,
                        None,
                    ),
                )
                event = (
                    await unit.execute(
                        text(
                            "SELECT bank_reference,amount_rial,text_digest,"
                            "parser_revision_id,receiving_realm_id,"
                            "original_provider_timestamp_ms,origin_kind,"
                            "origin_identity_sha256,"
                            "declared_notification_sha256 "
                            "FROM tbl_sms_events WHERE id=1"
                        )
                    )
                ).one()
                self.assertEqual(
                    tuple(event),
                    (
                        "prior-bank-reference",
                        240000,
                        "a" * 64,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                    ),
                )
                destination = (
                    await unit.execute(
                        text(
                            "SELECT encrypted_details,revision,"
                            "receiving_alias_id "
                            "FROM tbl_payment_destinations WHERE id=1"
                        )
                    )
                ).one()
                self.assertEqual(
                    tuple(destination),
                    (
                        "opaque-prior-destination",
                        1,
                        None,
                    ),
                )
                wallet = (
                    await unit.execute(
                        text(
                            "SELECT w.balance_rial,e.amount_rial,"
                            "e.balance_after_rial,"
                            "e.reference FROM tbl_wallets w "
                            "JOIN tbl_wallet_entries e "
                            "ON e.wallet_id=w.id WHERE w.id=1"
                        )
                    )
                ).one()
                self.assertEqual(
                    tuple(wallet),
                    (
                        240000,
                        240000,
                        240000,
                        "prior-origin-migration-credit",
                    ),
                )
                admissions = (
                    (
                        await unit.execute(
                            text(
                                "SELECT `key` FROM tbl_sms_origin_admissions "
                                "ORDER BY `key`"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                self.assertEqual(
                    admissions, ["policy_creation", "settlement_identity"]
                )
                self.assertEqual(
                    (
                        await unit.execute(
                            text("SELECT COUNT(*) FROM tbl_sms_settlements")
                        )
                    ).scalar_one(),
                    0,
                )
                self.assertEqual(
                    (
                        await unit.execute(
                            text(
                                "SELECT COUNT(*) "
                                "FROM tbl_sms_settlement_claims"
                            )
                        )
                    ).scalar_one(),
                    0,
                )
            with patch.dict(
                os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
            ):
                await asyncio.to_thread(command.downgrade, migration, PRIOR)
                await asyncio.to_thread(command.upgrade, migration, CURRENT)
            async with target.uow() as unit:
                await unit.execute(
                    text(
                        "INSERT INTO tbl_receiving_realms "
                        "(realm_key,title,is_active,origin_mode_enabled,"
                        "origin_requirement_since_ms,revision) VALUES "
                        "('11111111-1111-1111-1111-111111111111',"
                        "'Synthetic immutable realm',1,1,1790841600000,1)"
                    )
                )
                await unit.commit()
            with patch.dict(
                os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "Cannot discard SMS"
                ):
                    await asyncio.to_thread(
                        command.downgrade, migration, PRIOR
                    )
            async with target.uow() as unit:
                self.assertEqual(
                    (
                        await unit.execute(
                            text("SELECT version_num FROM alembic_version")
                        )
                    ).scalar_one(),
                    CURRENT,
                )
                self.assertEqual(
                    (
                        await unit.execute(
                            text(
                                "SELECT origin_requirement_since_ms "
                                "FROM tbl_receiving_realms"
                            )
                        )
                    ).scalar_one(),
                    1790841600000,
                )
                self.assertEqual(
                    (
                        await unit.execute(
                            text(
                                "SELECT balance_rial "
                                "FROM tbl_wallets WHERE id=1"
                            )
                        )
                    ).scalar_one(),
                    240000,
                )
        finally:
            await target.dispose()
            async with maintenance.uow() as unit:
                await unit.execute(text(f"DROP DATABASE `{schema}`"))
            await maintenance.dispose()
