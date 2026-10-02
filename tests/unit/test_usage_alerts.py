from __future__ import annotations

import asyncio
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from aiogram import Bot

from bot.infra.db.access import MysqlAccessRepository
from bot.jobs.runtime import usage_warning_scheduler
from bot.jobs.schedulers import (
    NodeReconcileJob,
    PaymentRecheckJob,
    ProvisionDeliveryDispatcher,
    ProvisionDeliveryJob,
    UsageWarningDispatcher,
    UsageWarningJob,
)
from bot.models.access import ProvisionDelivery, UsageAlert
from bot.services.node import NodeReconciler
from bot.services.payments import PaymentVerificationService


class UsageAlertTests(IsolatedAsyncioTestCase):
    async def test_payment_recheck_uses_papilio_scheduler_without_browser_callback(self) -> None:
        repository = AsyncMock(spec=MysqlAccessRepository)
        repository.claim_alerts.return_value = []
        verification = AsyncMock(spec=PaymentVerificationService)
        verification.recheck_pending.return_value = 1
        bot = Bot("123456:TEST_TOKEN")
        try:
            async with usage_warning_scheduler(repository, bot, payments=verification):
                handle = await PaymentRecheckJob.enqueue()
                result = await handle.wait_result(timeout=5)
            self.assertFalse(result.is_err)
            self.assertEqual(result.return_value, 1)
            verification.recheck_pending.assert_awaited_once()
        finally:
            await bot.session.close()
    async def test_dispatcher_sends_80_percent_once_and_marks_outbox(self) -> None:
        repository = AsyncMock(spec=MysqlAccessRepository)
        repository.claim_alerts.return_value = [
            UsageAlert(5, "order", 77, 8 * 1024**3, 10 * 1024**3)
        ]
        bot = AsyncMock(spec=Bot)
        dispatcher = UsageWarningDispatcher(repository, bot)
        self.assertEqual(await dispatcher.send_pending(), 1)
        bot.send_message.assert_awaited_once()
        self.assertEqual(bot.send_message.await_args.args[0], 77)
        self.assertIn("۸۰٪", bot.send_message.await_args.args[1])
        repository.mark_alert_sent.assert_awaited_once_with(5)
        repository.release_alert.assert_not_awaited()

    async def test_papilio_tasks_memory_job_executes_in_same_process(self) -> None:
        repository = AsyncMock(spec=MysqlAccessRepository)
        repository.claim_alerts.return_value = []
        bot = Bot("123456:TEST_TOKEN")
        try:
            async with usage_warning_scheduler(repository, bot):
                handle = await UsageWarningJob.enqueue()
                result = await handle.wait_result(timeout=5)
            self.assertFalse(result.is_err)
            self.assertEqual(result.return_value, 0)
            repository.claim_alerts.assert_awaited_once()
        finally:
            await bot.session.close()

    async def test_node_reconcile_job_is_registered_with_warning_job(self) -> None:
        repository = AsyncMock(spec=MysqlAccessRepository)
        repository.claim_alerts.return_value = []
        reconciler = AsyncMock(spec=NodeReconciler)
        bot = Bot("123456:TEST_TOKEN")
        try:
            async with usage_warning_scheduler(repository, bot, reconciler):
                node_handle = await NodeReconcileJob.enqueue()
                warning_handle = await UsageWarningJob.enqueue()
                node_result = await node_handle.wait_result(timeout=5)
                warning_result = await warning_handle.wait_result(timeout=5)
            self.assertFalse(node_result.is_err)
            self.assertFalse(warning_result.is_err)
            # The 2-second beat may also fire while the explicitly enqueued job runs.
            reconciler.run_once.assert_awaited()
        finally:
            await bot.session.close()

    async def test_recurring_node_job_runs_without_manual_enqueue(self) -> None:
        repository = AsyncMock(spec=MysqlAccessRepository)
        repository.claim_alerts.return_value = []
        reconciler = AsyncMock(spec=NodeReconciler)
        triggered = asyncio.Event()

        async def mark_run() -> None:
            triggered.set()

        reconciler.run_once.side_effect = mark_run
        bot = Bot("123456:TEST_TOKEN")
        try:
            async with usage_warning_scheduler(repository, bot, reconciler):
                await asyncio.wait_for(triggered.wait(), timeout=4)
            reconciler.run_once.assert_awaited()
        finally:
            await bot.session.close()

    async def test_delivery_outbox_sends_qr_and_both_links_once(self) -> None:
        from tests.unit.test_access import MemoryAccessRepository

        access = MemoryAccessRepository().access
        repository = AsyncMock(spec=MysqlAccessRepository)
        repository.claim_deliveries.return_value = [ProvisionDelivery(access.subscription_id, access)]
        bot = AsyncMock(spec=Bot)
        dispatcher = ProvisionDeliveryDispatcher(repository, bot, "https://sub.example")
        with patch.object(dispatcher._qr, "render", new_callable=AsyncMock) as render:
            render.return_value = b"png"
            self.assertEqual(await dispatcher.send_pending(), 1)
            assert render.await_args is not None
            self.assertTrue(render.await_args.args[0].startswith("https://sub.example/s/private-token#"))
        bot.send_photo.assert_awaited_once()
        self.assertEqual(bot.send_message.await_count, 2)
        self.assertIn("VLESS", bot.send_message.await_args_list[0].args[1])
        self.assertIn("VMess", bot.send_message.await_args_list[1].args[1])
        repository.mark_delivery_sent.assert_awaited_once_with(access.subscription_id)

    async def test_delivery_job_is_registered_with_node_job(self) -> None:
        repository = AsyncMock(spec=MysqlAccessRepository)
        repository.claim_alerts.return_value = []
        repository.claim_deliveries.return_value = []
        reconciler = AsyncMock(spec=NodeReconciler)
        bot = Bot("123456:TEST_TOKEN")
        try:
            async with usage_warning_scheduler(
                repository, bot, reconciler, "https://sub.example"
            ):
                handle = await ProvisionDeliveryJob.enqueue()
                result = await handle.wait_result(timeout=5)
            self.assertFalse(result.is_err)
            self.assertEqual(result.return_value, 0)
        finally:
            await bot.session.close()
