from __future__ import annotations

import asyncio
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from aiogram import Bot
from dishka import Provider, Scope, make_async_container, provide

from papilio_proxy.apps.scheduler import run_schedulers
from papilio_proxy.modules.network.nodes.app.services import NodeReconciler
from papilio_proxy.modules.network.nodes.schedulers import NodeReconcileJob
from papilio_proxy.modules.network.subscriptions.domain.entities import (
    ProvisionDelivery,
    UsageAlert,
)
from papilio_proxy.modules.network.subscriptions.infra.repository import MysqlAccessRepository
from papilio_proxy.modules.network.subscriptions.schedulers import (
    ProvisionDeliveryDispatcher,
    ProvisionDeliveryJob,
    UsageWarningDispatcher,
    UsageWarningJob,
)
from papilio_proxy.modules.sales.payments.infra.repository import MysqlPaymentRepository
from papilio_proxy.modules.sales.payments.schedulers import ReceiptDecisionJob


class JobsProvider(Provider):
    scope = Scope.APP

    def __init__(
        self, repository: MysqlAccessRepository, bot: Bot, reconciler: NodeReconciler | None = None
    ) -> None:
        super().__init__()
        self.repository, self.bot, self.reconciler = repository, bot, reconciler
        self.payments = AsyncMock(spec=MysqlPaymentRepository)
        self.payments.claim_notifications.return_value = []

    @provide
    def usage(self) -> UsageWarningJob:
        return UsageWarningJob(UsageWarningDispatcher(self.repository, self.bot))

    @provide
    def delivery(self) -> ProvisionDeliveryJob:
        return ProvisionDeliveryJob(
            ProvisionDeliveryDispatcher(self.repository, self.bot, "https://sub.example")
        )

    @provide
    def nodes(self) -> NodeReconcileJob:
        return NodeReconcileJob(self.reconciler)

    @provide
    def notices(self) -> ReceiptDecisionJob:
        return ReceiptDecisionJob(self.payments, self.bot)


class UsageAlertTests(IsolatedAsyncioTestCase):
    async def test_dispatcher_sends_80_percent_and_marks_outbox(self) -> None:
        repository = AsyncMock(spec=MysqlAccessRepository)
        repository.claim_alerts.return_value = [
            UsageAlert(5, "order", 77, 8 * 1024**3, 10 * 1024**3)
        ]
        bot = AsyncMock(spec=Bot)
        self.assertEqual(await UsageWarningDispatcher(repository, bot).send_pending(), 1)
        bot.send_message.assert_awaited_once()
        self.assertIn("۸۰٪", bot.send_message.await_args.args[1])
        repository.mark_alert_sent.assert_awaited_once_with(5)
        repository.release_alert.assert_not_awaited()

    async def test_native_scheduler_registers_all_jobs_without_payment_approval(self) -> None:
        repository = AsyncMock(spec=MysqlAccessRepository)
        repository.claim_alerts.return_value = []
        repository.claim_deliveries.return_value = []
        reconciler = AsyncMock(spec=NodeReconciler)
        bot = AsyncMock(spec=Bot)
        provider = JobsProvider(repository, bot, reconciler)
        async with make_async_container(provider) as container, run_schedulers(container):
            for job in (
                UsageWarningJob,
                ProvisionDeliveryJob,
                NodeReconcileJob,
                ReceiptDecisionJob,
            ):
                handle = await job.enqueue()
                result = await handle.wait_result(timeout=5)
                self.assertFalse(result.is_err)
        reconciler.run_once.assert_awaited()
        provider.payments.claim_notifications.assert_awaited()
        provider.payments.review.assert_not_awaited()

    async def test_recurring_node_job_runs_without_manual_enqueue(self) -> None:
        repository = AsyncMock(spec=MysqlAccessRepository)
        repository.claim_alerts.return_value = []
        repository.claim_deliveries.return_value = []
        reconciler = AsyncMock(spec=NodeReconciler)
        triggered = asyncio.Event()

        async def mark_run() -> None:
            triggered.set()

        reconciler.run_once.side_effect = mark_run
        async with (
            make_async_container(
                JobsProvider(repository, AsyncMock(spec=Bot), reconciler)
            ) as container,
            run_schedulers(container),
        ):
            await asyncio.wait_for(triggered.wait(), timeout=4)

    async def test_delivery_outbox_sends_qr_and_both_links(self) -> None:
        from tests.unit.test_access import MemoryAccessRepository

        access = MemoryAccessRepository().access
        repository = AsyncMock(spec=MysqlAccessRepository)
        repository.claim_deliveries.return_value = [
            ProvisionDelivery(access.subscription_id, access)
        ]
        bot = AsyncMock(spec=Bot)
        dispatcher = ProvisionDeliveryDispatcher(repository, bot, "https://sub.example")
        with patch.object(dispatcher._qr, "render", new_callable=AsyncMock) as render:
            render.return_value = b"png"
            self.assertEqual(await dispatcher.send_pending(), 1)
            assert render.await_args is not None
            self.assertTrue(
                render.await_args.args[0].startswith("https://sub.example/s/private-token#")
            )
        bot.send_photo.assert_awaited_once()
        self.assertEqual(bot.send_message.await_count, 2)
        self.assertIn("vless://", bot.send_message.await_args_list[0].args[1])
        self.assertIn("vmess://", bot.send_message.await_args_list[1].args[1])
        repository.mark_delivery_sent.assert_awaited_once_with(access.subscription_id)
