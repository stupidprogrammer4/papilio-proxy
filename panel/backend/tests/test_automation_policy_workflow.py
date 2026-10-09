import asyncio
from unittest.mock import patch
from uuid import uuid4

import httpx
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.uow import MySQLUnitOfWork
from papilio_tasks.infra.taskiq.sources.backends.redis import RedisSource
from sqlalchemy import text
from sqlalchemy.engine import make_url

from src.modules.operations.automation.domain.dtos import ScheduleKey
from src.modules.operations.automation.interfaces import (
    IAutomationPolicyQuery,
    IAutomationRegistrationCommand,
)
from tests.test_automation_workflow import TEST_URL, AutomationWorkflowFixture


class AutomationPolicyWorkflowTest(AutomationWorkflowFixture):
    async def asyncSetUp(self):
        self.schema = (
            "papilio_upgrade_test_automation_policy_" + uuid4().hex[:12]
        )
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
        url = make_url(str(TEST_URL)).set(database=self.schema)
        with patch(
            "tests.test_automation_workflow.TEST_URL",
            url.render_as_string(hide_password=False),
        ):
            await super().asyncSetUp()

    async def asyncTearDown(self):
        await super().asyncTearDown()
        async with self.maintenance.uow() as unit:
            await unit.execute(text(f"DROP DATABASE `{self.schema}`"))
        await self.maintenance.dispose()

    async def policy(self, key="payments"):
        return (await self.get(f"/v1/admin/automation/schedules/{key}"))[
            "data"
        ]

    def values(self, row):
        return {
            name: row[name]
            for name in (
                "mode",
                "interval_seconds",
                "enabled",
                "cron",
                "timezone",
                "batch_size",
                "recheck_seconds",
            )
        }

    async def write(self, row, values):
        response = await self.client.put(
            f"/v1/admin/automation/schedules/{row['key']}",
            headers=self.headers,
            json={
                "expected_revision": row["revision"],
                "values": values,
                "reason": "تغییر زمان‌بندی آزمون",
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    async def test_revision_scope_validation_and_paged_history(self):
        all_rows = (await self.get("/v1/admin/automation/schedules"))["data"]
        self.assertEqual(len(all_rows), len(ScheduleKey))
        original = await self.policy()
        changed = await self.write(
            original,
            {
                **self.values(original),
                "enabled": False,
                "timezone": "Asia/Tehran",
                "batch_size": 1,
            },
        )
        self.assertEqual(changed["revision"], 1)
        self.assertIsNone(changed["applied_revision"])
        stale = await self.client.put(
            "/v1/admin/automation/schedules/payments",
            headers=self.headers,
            json={
                "expected_revision": 0,
                "values": self.values(original),
                "reason": "درخواست قدیمی",
            },
        )
        self.assertEqual(stale.status_code, 409)
        invalid_values = [
            ("cron", "*/0 * * * *"),
            ("cron", "* 99 * * *"),
            ("timezone", "missing/timezone"),
            (
                "batch_size",
                self.settings.operations.automation_max_batch_size + 1,
            ),
            ("recheck_seconds", None),
        ]
        rejected = await asyncio.gather(
            *(
                self.client.put(
                    "/v1/admin/automation/schedules/payments",
                    headers=self.headers,
                    json={
                        "expected_revision": 1,
                        "values": {**self.values(changed), field: value},
                        "reason": "سیاست نامعتبر",
                    },
                )
                for field, value in invalid_values
            )
        )
        for (field, _), invalid in zip(invalid_values, rejected, strict=True):
            self.assertEqual(
                invalid.status_code,
                400 if field in {"batch_size", "recheck_seconds"} else 422,
            )
        second = await self.write(
            changed, {**self.values(changed), "enabled": True}
        )
        history = await self.get(
            "/v1/admin/automation/schedules/payments/history?per_page=1"
        )
        self.assertEqual(history["meta"]["pager"]["total_items"], 2)
        self.assertEqual(history["data"][0]["revision"], second["revision"])
        self.assertEqual(
            (
                await self.get(
                    "/v1/admin/automation/schedules/payments/history?per_page=1&page=2"
                )
            )["data"][0]["revision"],
            1,
        )
        staff = await self.post(
            "/v1/admin/staff",
            {
                "username": "schedule_reader_" + self.suffix,
                "password": "readonly888",
                "is_active": True,
                "scopes": ["payments:read"],
            },
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="https://admin.example.com",
        ) as reader:
            login = await reader.post(
                "/v1/admin/auth/login",
                headers={"Origin": self.settings.public.admin_origin},
                json={
                    "username": staff["username"],
                    "password": "readonly888",
                },
            )
            self.assertEqual(login.status_code, 200)
            headers = {
                "Origin": self.settings.public.admin_origin,
                "X-CSRF-Token": login.json()["csrf_token"],
            }
            listed = await reader.get("/v1/admin/automation/schedules")
            self.assertEqual(
                [row["key"] for row in listed.json()["data"]], ["payments"]
            )
            self.assertEqual(
                (
                    await reader.get("/v1/admin/automation/schedules/nodes")
                ).status_code,
                403,
            )
            denied = await reader.put(
                "/v1/admin/automation/schedules/payments",
                headers=headers,
                json={
                    "expected_revision": second["revision"],
                    "values": self.values(original),
                    "reason": "ویرایش بدون مجوز",
                },
            )
            self.assertEqual(denied.status_code, 403)

    async def test_native_store_reconciliation_restores_deleted_state(self):
        current = await self.policy()
        values = {
            **self.values(current),
            "cron": "*/5 * * * *",
            "timezone": "Asia/Tehran",
            "batch_size": 2,
        }
        current = await self.write(current, values)
        from papilio_tasks.apps.schedulers.redis import create_app

        from src.config.providers import task_providers
        from src.modules.billing.reviews.tasks.schedulers.checks import (
            ScanPaymentReview,
        )

        native = create_app(
            self.settings.tasks.scheduler,
            providers=task_providers(self.settings),
            modules=self.settings.app.modules,
        )
        self.addAsyncCleanup(native.stop)
        task = ScanPaymentReview.task()
        async with self.app.state.dishka_container() as scope:
            command = await scope.get(IAutomationRegistrationCommand)
            source = await scope.get(RedisSource)
            self.assertEqual(
                await command.reconcile(ScheduleKey.PAYMENTS, task), 1
            )
            inventory = await source.list_schedules()
            identifier = (
                self.settings.operations.automation_registration_prefix
                + "payments"
            )
            stored = next(
                row for row in inventory if row.schedule_id == identifier
            )
            self.assertEqual(stored.cron, "*/5 * * * *")
            self.assertEqual(stored.cron_offset, "Asia/Tehran")
            self.assertEqual(stored.kwargs, {"expected_revision": 1})
            self.assertEqual(
                str(stored.labels["retry_on_error"]).lower(), "true"
            )
            self.assertEqual(
                int(stored.labels["max_retries"]),
                self.settings.operations.automation_retry_attempts,
            )
            await source.delete_schedule(identifier)
        async with self.app.state.dishka_container() as scope:
            command = await scope.get(IAutomationRegistrationCommand)
            self.assertEqual(
                await command.reconcile(ScheduleKey.PAYMENTS, task), 1
            )
            source = await scope.get(RedisSource)
            self.assertEqual(len(await source.list_schedules()), 1)
        current = await self.policy()
        self.assertEqual(current["applied_revision"], 1)
        maximum = self.settings.operations.automation_max_batch_size
        self.settings.operations.automation_max_batch_size = 1
        constrained = await self.policy()
        self.assertFalse(constrained["capacity_valid"])
        async with self.app.state.dishka_container() as scope:
            command = await scope.get(IAutomationRegistrationCommand)
            await command.reconcile(ScheduleKey.PAYMENTS, task)
            source = await scope.get(RedisSource)
            self.assertEqual(await source.list_schedules(), [])
        self.settings.operations.automation_max_batch_size = maximum
        async with self.app.state.dishka_container() as scope:
            command = await scope.get(IAutomationRegistrationCommand)
            await command.reconcile(ScheduleKey.PAYMENTS, task)
            source = await scope.get(RedisSource)
            self.assertEqual(len(await source.list_schedules()), 1)
        current = await self.write(
            current,
            {
                **self.values(current),
                "mode": "interval",
                "interval_seconds": 15,
                "cron": None,
                "timezone": None,
            },
        )
        async with self.app.state.dishka_container() as scope:
            command = await scope.get(IAutomationRegistrationCommand)
            self.assertEqual(
                await command.reconcile(ScheduleKey.PAYMENTS, task), 2
            )
            source = await scope.get(RedisSource)
            scheduled = (await source.list_schedules())[0]
            self.assertEqual(scheduled.interval, 15)
            self.assertIsNone(scheduled.cron)
            self.assertIsNone(scheduled.cron_offset)
            self.assertEqual(scheduled.kwargs, {"expected_revision": 2})
        current = await self.policy()
        self.assertEqual(current["applied_revision"], 2)
        current = await self.write(
            current, {**self.values(current), "enabled": False}
        )
        async with self.app.state.dishka_container() as scope:
            command = await scope.get(IAutomationRegistrationCommand)
            self.assertEqual(
                await command.reconcile(ScheduleKey.PAYMENTS, task), 3
            )
            source = await scope.get(RedisSource)
            self.assertEqual(await source.list_schedules(), [])
            policies = await scope.get(IAutomationPolicyQuery)
            self.assertFalse(
                (await policies.schedule(ScheduleKey.PAYMENTS)).values.enabled
            )

    async def test_batch_limits_pause_and_obsolete_queued_scan(self):
        from src.modules.billing.reviews.interfaces import IPaymentReviewQuery
        from src.modules.billing.reviews.tasks.schedulers.checks import (
            ScanPaymentReview,
        )

        customer = await self.post(
            "/v1/admin/customers", {"display_name": "پرداخت‌های زمان‌بندی"}
        )
        await asyncio.gather(
            *(
                self.post(
                    "/v1/admin/payments/topups",
                    {
                        "customer_id": customer["id"],
                        "amount_rial": 100000 + index,
                    },
                )
                for index in range(3)
            )
        )
        original = await self.policy()
        current = await self.write(
            original,
            {**self.values(original), "batch_size": 1, "recheck_seconds": 1},
        )
        async with self.app.state.dishka_container() as scope:
            query = await scope.get(IPaymentReviewQuery)
            policies = await scope.get(IAutomationPolicyQuery)
            self.assertEqual(len(await query.due_ids()), 1)
            self.assertEqual(
                await ScanPaymentReview(query, policies).run(
                    expected_revision=0
                ),
                0,
            )
        await self.write(current, {**self.values(current), "enabled": False})
        async with self.app.state.dishka_container() as scope:
            query = await scope.get(IPaymentReviewQuery)
            policies = await scope.get(IAutomationPolicyQuery)
            self.assertEqual(await query.due_ids(), [])
            self.assertEqual(
                await ScanPaymentReview(query, policies).run(
                    expected_revision=1
                ),
                0,
            )
