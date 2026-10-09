import asyncio
import json
import os
import re
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import event, insert, text

from src.modules.operations.notifications.infra.mysql import (
    NotificationRepository,
)
from src.modules.operations.notifications.infra.tables import NotificationTable
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowTest,
)


class PerformanceWorkflowTest(StaffAdministrationWorkflowTest):
    async def test_populated_expired_lease_recovery_plan_and_upgrade(self):
        migration = Config("alembic.ini")
        migration.set_main_option(
            "sqlalchemy.url",
            self.connection.engine.url.render_as_string(hide_password=False),
        )
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(
                command.downgrade, migration, "0040_sms_devices"
            )
        customer = await self.post(
            "/v1/admin/customers", {"display_name": "Recovery plan fixture"}
        )
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        population = 20000
        expired = 10
        rows = [
            {
                "customer_id": customer["id"],
                "event_key": f"lease-fixture-{number}",
                "event_hash": "a" * 64,
                "kind": "payment_approved",
                "title": "Recovery fixture",
                "body": "Fixture",
                "inbox_visible": True,
                "is_read": False,
                "status": "processing",
                "revision": 1,
                "attempts": 1,
                "retry_budget_used": 0,
                "next_attempt_at": now,
                "lease_until": now
                + timedelta(
                    seconds=-60 if number >= population - expired else 3600
                ),
            }
            for number in range(population)
        ]
        async with self.connection.uow() as unit:
            await unit.execute(insert(NotificationTable), rows)
            await unit.commit()
        await self.analyze_notifications()
        before_ids, before_plan, before_scanned = await self.recovery_plan(
            now, expired
        )
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(command.upgrade, migration, "head")
        await self.analyze_notifications()
        after_ids, after_plan, after_scanned = await self.recovery_plan(
            now, expired
        )
        self.assertEqual(after_ids, before_ids)
        self.assertEqual(len(after_ids), expired)
        async with self.connection.uow() as fresh:
            count = await fresh.execute(
                text("SELECT COUNT(*) FROM tbl_notifications")
            )
            self.assertEqual(count.scalar_one(), population)
        print(
            "RECOVERY_PLAN "
            + json.dumps(
                {
                    "population": population,
                    "expired": expired,
                    "before": before_plan,
                    "after": after_plan,
                }
            )
        )
        self.assertEqual(before_scanned, population)
        self.assertLessEqual(after_scanned, expired)

    async def analyze_notifications(self):
        async with self.connection.uow() as unit:
            await unit.execute(text("ANALYZE TABLE tbl_notifications"))

    async def recovery_plan(self, now, limit):
        statements = []

        def capture(connection, clause, multiparams, params, options):
            if str(clause).startswith("SELECT"):
                statements.append(clause)

        engine = self.connection.engine.sync_engine
        event.listen(engine, "before_execute", capture)
        try:
            async with self.connection.uow() as unit:
                ids = await NotificationRepository(unit).due_ids(
                    now, (), "processing", (), limit
                )
        finally:
            event.remove(engine, "before_execute", capture)
        (statement,) = statements
        sql = str(
            statement.compile(
                dialect=engine.dialect, compile_kwargs={"literal_binds": True}
            )
        )
        async with self.connection.uow() as independent:
            explained = await independent.execute(
                text("EXPLAIN FORMAT=JSON " + sql)
            )
            plan = json.loads(explained.scalar_one())
            analyzed = await independent.execute(
                text("EXPLAIN ANALYZE " + sql)
            )
            execution = analyzed.scalar_one()
            print("RECOVERY_EXECUTION " + execution)
        scans = re.findall(r"rows=(\d+) loops=(\d+)\)", execution)
        scanned = int(scans[-1][0]) * int(scans[-1][1])
        return ids, plan, scanned
