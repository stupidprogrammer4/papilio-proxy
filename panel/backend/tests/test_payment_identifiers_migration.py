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
PRIOR = "0052_sms_origin_settlement"
CURRENT = "0053_payment_amount_identifiers"


@skipUnless(TEST_URL, "Requires isolated MySQL")
class PaymentIdentifiersMigrationTest(IsolatedAsyncioTestCase):
    async def test_populated_origin_credit_and_provenance_survive(self):
        schema = "papilio_amount_migration_test_" + uuid4().hex[:12]
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
                        "INSERT INTO tbl_customers(id,display_name,"
                        "is_active) VALUES(1,'Synthetic prior "
                        "payer',1)"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_receiving_realms(id,"
                        "realm_key,title,is_active,"
                        "origin_mode_enabled,"
                        "origin_requirement_since_ms,revision) "
                        "VALUES(1,"
                        "'22222222-2222-2222-2222-222222222222',"
                        "'Synthetic prior realm',1,1,1790841600000,"
                        "3)"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_receiving_aliases(id,"
                        "realm_id,account_sha256,kind,"
                        "normalization_revision) VALUES(1,1,"
                        "REPEAT('b',64),'card',1)"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_payment_destinations(id,"
                        "title,kind,encrypted_details,is_active,"
                        "receiving_alias_id,revision) VALUES(1,"
                        "'Synthetic prior card','card',"
                        "'opaque-prior-details',1,1,4)"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_sms_devices(id,label,"
                        "encrypted_key,senders_json,is_active,"
                        "revision,expires_at,approval_mode,"
                        "destination_id,settlement_identity_mode) "
                        "VALUES(1,'Synthetic prior phone',"
                        "'opaque-prior-key','[\"SYNTHETIC\"]',1,5,"
                        "'2030-01-01','unique_sms',1,"
                        "'trusted_origin_fingerprint')"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_sms_events(id,device_id,"
                        "event_id,sender,text_digest,amount_rial,"
                        "sent_at,receiving_realm_id,"
                        "receiving_alias_id,captured_destination_id,"
                        "captured_destination_revision,direction,"
                        "origin_kind,original_provider_timestamp_ms,"
                        "origin_identity_sha256,"
                        "declared_notification_sha256) VALUES(1,1,"
                        "'synthetic-prior-event','SYNTHETIC',"
                        "REPEAT('c',64),1051234,'2026-10-01 "
                        "12:00:00',1,1,1,4,'deposit','direct_sms',"
                        "1790841600000,REPEAT('d',64),REPEAT('e',"
                        "64))"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_topups(id,customer_id,"
                        "amount_rial,status,approved_by_device_id,"
                        "approved_by_sms_id,destination_id,"
                        "request_key,encrypted_instruction,"
                        "receiving_realm_id,receiving_alias_id,"
                        "captured_destination_revision) VALUES(1,1,"
                        "1051234,'approved',1,1,1,"
                        "'synthetic-prior-request',"
                        "'opaque-prior-instruction',1,1,4)"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_wallets(id,customer_id,"
                        "balance_rial) VALUES(1,1,1051234)"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_wallet_entries(wallet_id,"
                        "amount_rial,balance_after_rial,reference,"
                        "reason) VALUES(1,1051234,1051234,"
                        "'synthetic-prior-credit','approved_topup')"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_sms_settlements(id,"
                        "topup_id,sms_event_id,device_id,"
                        "receiving_realm_id,evidence_kind) VALUES(1,"
                        "1,1,1,1,'trusted_sms_origin')"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO "
                        "tbl_sms_settlement_claims(settlement_id,"
                        "identity_kind,identity_key) VALUES(1,"
                        "'trusted_sms_origin',REPEAT('d',64))"
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
                            "SELECT amount_rial,requested_amount_rial,"
                            "payment_identifier_mode,"
                            "payment_identifier_code4,status,"
                            "bank_reference,encrypted_instruction,"
                            "receiving_realm_id,receiving_alias_id,"
                            "captured_destination_revision FROM "
                            "tbl_topups WHERE id=1"
                        )
                    )
                ).one()
                self.assertEqual(
                    tuple(row),
                    (
                        1051234,
                        None,
                        "exact_requested",
                        None,
                        "approved",
                        None,
                        "opaque-prior-instruction",
                        1,
                        1,
                        4,
                    ),
                )
                bindings = (
                    await unit.execute(
                        text(
                            "SELECT r.origin_requirement_since_ms,"
                            "r.revision,d.encrypted_details,d.revision,"
                            "p.encrypted_key,p.revision,"
                            "p.settlement_identity_mode FROM "
                            "tbl_receiving_realms r JOIN "
                            "tbl_payment_destinations d ON d.id=1 JOIN "
                            "tbl_sms_devices p ON p.id=1 WHERE r.id=1"
                        )
                    )
                ).one()
                self.assertEqual(
                    tuple(bindings),
                    (
                        1790841600000,
                        3,
                        "opaque-prior-details",
                        4,
                        "opaque-prior-key",
                        5,
                        "trusted_origin_fingerprint",
                    ),
                )
                credit = (
                    await unit.execute(
                        text(
                            "SELECT w.balance_rial,e.amount_rial,"
                            "e.balance_after_rial,e.reference FROM "
                            "tbl_wallets w JOIN tbl_wallet_entries e ON "
                            "e.wallet_id=w.id WHERE w.id=1"
                        )
                    )
                ).one()
                self.assertEqual(
                    tuple(credit),
                    (1051234, 1051234, 1051234, "synthetic-prior-credit"),
                )
                proof = (
                    await unit.execute(
                        text(
                            "SELECT s.evidence_kind,c.identity_kind,"
                            "c.identity_key,e.origin_identity_sha256,"
                            "e.declared_notification_sha256 FROM "
                            "tbl_sms_settlements s JOIN "
                            "tbl_sms_settlement_claims c ON "
                            "c.settlement_id=s.id JOIN tbl_sms_events e "
                            "ON e.id=s.sms_event_id WHERE s.id=1"
                        )
                    )
                ).one()
                self.assertEqual(
                    tuple(proof),
                    (
                        "trusted_sms_origin",
                        "trusted_sms_origin",
                        "d" * 64,
                        "d" * 64,
                        "e" * 64,
                    ),
                )
                self.assertEqual(
                    (
                        await unit.execute(
                            text(
                                "SELECT COUNT(*) FROM "
                                "tbl_payment_amount_reservations"
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
                        "INSERT INTO tbl_topups(id,customer_id,"
                        "amount_rial,requested_amount_rial,"
                        "payment_identifier_mode,"
                        "payment_identifier_code4,status,"
                        "destination_id,receiving_realm_id,"
                        "receiving_alias_id,"
                        "captured_destination_revision) VALUES(2,1,"
                        "2051234,2050000,'rial_suffix4','1234',"
                        "'pending',1,1,1,4)"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO "
                        "tbl_payment_amount_reservations(receiving_r"
                        "ealm_id,topup_id,requested_amount_rial,"
                        "payable_amount_rial,code4) VALUES(1,2,"
                        "2050000,2051234,'1234')"
                    )
                )
                await unit.commit()
            with patch.dict(
                os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "Cannot discard issued payable"
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
                                "SELECT payable_amount_rial FROM "
                                "tbl_payment_amount_reservations WHERE "
                                "topup_id=2"
                            )
                        )
                    ).scalar_one(),
                    2051234,
                )
                self.assertEqual(
                    (
                        await unit.execute(
                            text(
                                "SELECT balance_rial FROM tbl_wallets WHERE "
                                "id=1"
                            )
                        )
                    ).scalar_one(),
                    1051234,
                )
        finally:
            await target.dispose()
            async with maintenance.uow() as unit:
                await unit.execute(text(f"DROP DATABASE `{schema}`"))
            await maintenance.dispose()
