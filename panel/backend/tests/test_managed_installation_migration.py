"""Existing storage facts remain unverified across the native-name repair."""

import asyncio
from datetime import UTC, datetime, timedelta

from alembic import command
from alembic.config import Config
from papilio.infra.db.transaction import transaction
from sqlalchemy import text

from tests.test_managed_installation_workflow import (
    ManagedInstallationWorkflowFixture,
)


class ManagedInstallationMigrationTest(ManagedInstallationWorkflowFixture):
    async def migrate(self, target, *, downgrade=False):
        database = self.settings.db
        assert database is not None
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", database.dsn)
        operation = command.downgrade if downgrade else command.upgrade
        await asyncio.to_thread(operation, config, target)

    async def test_populated_native_epoch_rename_preflights_and_preserves_refs(
        self,
    ):
        _, subscription, node, configuration = await self.setup_installation()
        issued = await self.issue()
        self.assertEqual(issued.status_code, 200)
        installation = issued.json()["data"]["id"]
        async with self.connection.uow() as fresh:
            profile = (
                await fresh.execute(
                    text(
                        (
                            "SELECT id FROM tbl_profiles WHERE "
                            "configuration_id=:id"
                        )
                    ),
                    {"id": configuration["id"]},
                )
            ).scalar_one()
            manifest = (
                await fresh.execute(
                    text(
                        (
                            "SELECT encrypted_manifest FROM "
                            "tbl_managed_installations WHERE id=:id"
                        )
                    ),
                    {"id": installation},
                )
            ).scalar_one()
        grant = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/usage/grants",
            headers=self.node_headers,
            json={
                "profile_id": profile,
                "generation": 0,
                "request_key": "legacy_migration_" + self.suffix,
                "requested_bytes": 128,
            },
        )
        self.assertEqual(grant.status_code, 200, grant.text)
        grant_id = grant.json()["data"]["id"]
        await self.migrate("0057_ip_session_precision", downgrade=True)
        async with self.connection.uow() as unit:
            await unit.execute(
                text(
                    "CREATE TABLE tbl_managed_epoches (id BIGINT PRIMARY KEY)"
                )
            )
        with self.assertRaisesRegex(RuntimeError, "conflicting native"):
            await self.migrate("head")
        async with self.connection.uow() as unit:
            version = (
                await unit.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            ).scalar_one()
            columns = (
                await unit.execute(
                    text(
                        "SELECT COUNT(*) FROM information_schema.columns "
                        "WHERE table_schema=DATABASE() AND "
                        "table_name='tbl_managed_installations' AND "
                        "column_name='claim_hash'"
                    )
                )
            ).scalar_one()
            self.assertEqual(
                (version, columns), ("0057_ip_session_precision", 0)
            )
            await unit.execute(text("DROP TABLE tbl_managed_epoches"))
        timestamp = datetime.now(UTC).replace(tzinfo=None)
        epoch = "a" * 32
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        (
                            "INSERT INTO tbl_managed_installations "
                            "(node_id,core_id,runtime_revision_id,installation"
                            "_sha256,encrypted_manifest) SELECT "
                            "node_id,core_id,runtime_revision_id,:digest,encry"
                            "pted_manifest FROM tbl_managed_installations "
                            "WHERE id=:id"
                        )
                    ),
                    {"digest": "f" * 64, "id": installation},
                )
                other = (
                    await unit.execute(text("SELECT LAST_INSERT_ID()"))
                ).scalar_one()
                await unit.execute(
                    text(
                        (
                            "INSERT INTO tbl_managed_epochs "
                            "(installation_id,process_epoch,installed_closed_a"
                            "t,receipt_sha256,encrypted_receipt) VALUES "
                            "(:id,:epoch,:at,:sha,:receipt)"
                        )
                    ),
                    {
                        "id": installation,
                        "epoch": epoch,
                        "at": timestamp,
                        "sha": "b" * 64,
                        "receipt": "legacy-storage-receipt",
                    },
                )
                epoch_id = (
                    await unit.execute(text("SELECT LAST_INSERT_ID()"))
                ).scalar_one()
                await unit.execute(
                    text(
                        (
                            "INSERT INTO tbl_managed_epochs "
                            "(installation_id,process_epoch,installed_closed_a"
                            "t,receipt_sha256,encrypted_receipt) VALUES "
                            "(:id,:epoch,:at,:sha,:receipt)"
                        )
                    ),
                    {
                        "id": other,
                        "epoch": epoch,
                        "at": timestamp,
                        "sha": "c" * 64,
                        "receipt": "legacy-storage-duplicate",
                    },
                )
                duplicate = (
                    await unit.execute(text("SELECT LAST_INSERT_ID()"))
                ).scalar_one()
                await unit.execute(
                    text(
                        (
                            "INSERT INTO tbl_managed_barriers "
                            "(epoch_id,barrier_id,acceptance_id,snapshot_sha25"
                            "6,request_sha256,frozen_at,accepted_at,encrypted_"
                            "receipt) VALUES "
                            "(:epoch,:barrier,:acceptance,:sha,:request,:at,:a"
                            "t,:receipt)"
                        )
                    ),
                    {
                        "epoch": epoch_id,
                        "barrier": "d" * 32,
                        "acceptance": "e" * 32,
                        "sha": "d" * 64,
                        "request": "e" * 64,
                        "at": timestamp,
                        "receipt": "legacy-storage-barrier",
                    },
                )
                barrier = (
                    await unit.execute(text("SELECT LAST_INSERT_ID()"))
                ).scalar_one()
                await unit.execute(
                    text(
                        (
                            "INSERT INTO tbl_managed_windows "
                            "(epoch_id,grant_id,profile_id,subscription_id,gen"
                            "eration,window_id,request_key,request_sha256,wind"
                            "ow_sha256,baseline_upload_bytes,baseline_download"
                            "_bytes,allocated_bytes,issued_at,valid_until,pred"
                            "ecessor_id,encrypted_window) VALUES "
                            "(:epoch,:grant,:profile,:subscription,0,:window,:"
                            "request,:sha,:sha,0,0,128,:at,:until,:barrier,:pa"
                            "yload)"
                        )
                    ),
                    {
                        "epoch": epoch_id,
                        "grant": grant_id,
                        "profile": profile,
                        "subscription": subscription["id"],
                        "window": "f" * 32,
                        "request": "legacy_" + self.suffix,
                        "sha": "f" * 64,
                        "at": timestamp,
                        "until": timestamp + timedelta(seconds=60),
                        "barrier": barrier,
                        "payload": "legacy-storage-window",
                    },
                )
        with self.assertRaisesRegex(RuntimeError, "duplicate managed epochs"):
            await self.migrate("head")
        async with self.connection.uow() as fresh:
            version = (
                await fresh.execute(
                    text(("SELECT version_num FROM alembic_version"))
                )
            ).scalar_one()
            columns = (
                await fresh.execute(
                    text(
                        (
                            "SELECT COUNT(*) FROM information_schema.columns "
                            "WHERE table_schema=DATABASE() AND "
                            "table_name='tbl_managed_installations' AND "
                            "column_name='claim_hash'"
                        )
                    )
                )
            ).scalar_one()
            self.assertEqual(
                (version, columns), ("0057_ip_session_precision", 0)
            )
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(("DELETE FROM tbl_managed_epochs WHERE id=:id")),
                    {"id": duplicate},
                )
        await self.migrate("head")
        async with self.connection.uow() as fresh:
            existing = (
                await fresh.execute(
                    text(
                        (
                            "SELECT state,encrypted_manifest FROM "
                            "tbl_managed_installations WHERE id=:id"
                        )
                    ),
                    {"id": installation},
                )
            ).one()
            self.assertEqual(tuple(existing), ("legacy_unknown", manifest))
            references = (
                await fresh.execute(
                    text(
                        (
                            "SELECT "
                            "w.epoch_id,b.epoch_id,e.encrypted_receipt,w.encrypted"
                            "_window FROM tbl_managed_windows w JOIN "
                            "tbl_managed_epoches e ON e.id=w.epoch_id JOIN "
                            "tbl_managed_barriers b ON b.id=w.predecessor_id "
                            "WHERE w.grant_id=:id"
                        )
                    ),
                    {"id": grant_id},
                )
            ).one()
            self.assertEqual(
                tuple(references),
                (
                    epoch_id,
                    epoch_id,
                    "legacy-storage-receipt",
                    "legacy-storage-window",
                ),
            )
            foreign_keys = (
                (
                    await fresh.execute(
                        text(
                            (
                                "SELECT referenced_table_name FROM "
                                "information_schema.key_column_usage WHERE "
                                "table_schema=DATABASE() AND table_name IN "
                            "('tbl_managed_windows',"
                            "'tbl_managed_barriers') AND "
                                "column_name='epoch_id' AND "
                                "referenced_table_name IS NOT NULL"
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(
                foreign_keys, ["tbl_managed_epoches", "tbl_managed_epoches"]
            )
        replay = await self.issue()
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(
            replay.json()["error"]["message_code"],
            "managed_installation_legacy_unverified",
        )
        await self.migrate("0057_ip_session_precision", downgrade=True)
        await self.migrate("head")
        policy = self.settings.managed_adapter
        assert policy is not None
        self.settings.managed_adapter = policy.model_copy(
            update={"executable_sha256": "9" * 64}
        )
        new = await self.issue()
        self.assertEqual(new.status_code, 200)
        claimed = await self.client.post(
            f"{self.node_path}/{new.json()['data']['id']}/claim",
            headers=self.node_headers,
        )
        self.assertEqual(claimed.status_code, 200)
        with self.assertRaisesRegex(RuntimeError, "Cannot discard"):
            await self.migrate("0057_ip_session_precision", downgrade=True)
        async with self.connection.uow() as fresh:
            version = (
                await fresh.execute(
                    text(("SELECT version_num FROM alembic_version"))
                )
            ).scalar_one()
            self.assertEqual(version, "0058_managed_installation_claims")
            row = (
                await fresh.execute(
                    text(
                        (
                            "SELECT encrypted_receipt "
                            "FROM tbl_managed_epoches "
                            "WHERE id=:id"
                        )
                    ),
                    {"id": epoch_id},
                )
            ).scalar_one()
            self.assertEqual(row, "legacy-storage-receipt")
