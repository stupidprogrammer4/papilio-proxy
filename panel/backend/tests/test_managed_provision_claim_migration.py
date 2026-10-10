"""Populated native window preservation and immutable paid claim downgrade."""

import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from tests.test_managed_windows_workflow import ManagedWindowWorkflowFixture

PRIOR = "0058_managed_installation_claims"
CURRENT = "0059_managed_provision_claims"


class ManagedProvisionClaimMigrationTest(ManagedWindowWorkflowFixture):
    async def migrate(self, revision, *, downgrade=False):
        database = self.settings.db
        assert database is not None
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", database.dsn)
        operation = command.downgrade if downgrade else command.upgrade
        await asyncio.to_thread(operation, config, revision)

    async def window_storage(self, window_id):
        async with self.connection.uow() as fresh:
            rows = await fresh.execute(
                text(
                    "SELECT w.id,w.grant_id,w.window_sha256,"
                    "w.encrypted_window,w.request_sha256,w.provision_task_id,"
                    "g.allocated_bytes,g.is_closed,g.upload_bytes,"
                    "g.download_bytes,s.status,s.used_bytes "
                    "FROM tbl_managed_windows w JOIN tbl_usage_grants g "
                    "ON g.id=w.grant_id JOIN tbl_subscriptions s "
                    "ON s.id=w.subscription_id WHERE w.id=:id"
                ),
                {"id": window_id},
            )
            result = tuple(rows.one())
        return result

    async def test_populated_58_upgrade_preserves_original_window_replay(self):
        _, _, issued, _, body, path = await self.setup_window()
        await self.migrate(PRIOR, downgrade=True)
        before = await self.window_storage(issued["id"])
        self.assertEqual(before[5:], (None, 1024, 0, 0, 0, "active", 0))
        await self.migrate(CURRENT)
        after = await self.window_storage(issued["id"])
        self.assertEqual(after, before)
        async with self.connection.uow() as fresh:
            claim = await fresh.execute(
                text(
                    "SELECT encrypted_provision_claim FROM "
                    "tbl_managed_windows WHERE id=:id"
                ),
                {"id": issued["id"]},
            )
            self.assertIsNone(claim.scalar_one())
        replay = await self.client.post(
            path, headers=self.node_headers, json=body
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["data"], issued)
        self.assertEqual(
            replay.json()["data"]["original_window"],
            issued["original_window"],
        )
        self.assertEqual(await self.window_storage(issued["id"]), before)

    async def test_paid_claim_refuses_downgrade_before_ddl(self):
        self.paid_managed_fixture = True
        subscription, _, _, body, path, _ = await self.setup_closed()
        policy = self.settings.managed_adapter
        assert policy is not None
        self.settings.managed_adapter = policy.model_copy(
            update={
                "window_mode": "reserved",
                "paid_mode": "strict_admission",
            }
        )
        async with self.connection.uow() as fresh:
            task = await fresh.execute(
                text(
                    "SELECT t.id FROM tbl_provision_tasks t JOIN "
                    "tbl_provision_requests r ON r.id=t.request_id "
                    "WHERE r.subscription_id=:id"
                ),
                {"id": subscription["id"]},
            )
            body["provision_task_id"] = task.scalar_one()
        response = await self.client.post(
            path, headers=self.node_headers, json=body
        )
        self.assertEqual(response.status_code, 200, response.text)
        issued = response.json()["data"]
        before = await self.window_storage(issued["id"])
        with self.assertRaisesRegex(
            RuntimeError, "Cannot discard immutable paid managed claims"
        ):
            await self.migrate(PRIOR, downgrade=True)
        async with self.connection.uow() as fresh:
            version = await fresh.execute(
                text("SELECT version_num FROM alembic_version")
            )
            self.assertEqual(version.scalar_one(), CURRENT)
            columns = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.columns WHERE "
                    "table_schema=DATABASE() AND "
                    "table_name='tbl_managed_windows' AND "
                    "column_name='encrypted_provision_claim'"
                )
            )
            self.assertEqual(columns.scalar_one(), 1)
            claims = await fresh.execute(
                text(
                    "SELECT encrypted_provision_claim IS NOT NULL FROM "
                    "tbl_managed_windows WHERE id=:id"
                ),
                {"id": issued["id"]},
            )
            self.assertEqual(claims.scalar_one(), 1)
        self.assertEqual(await self.window_storage(issued["id"]), before)
        replay = await self.client.post(
            path, headers=self.node_headers, json=body
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["data"], issued)
