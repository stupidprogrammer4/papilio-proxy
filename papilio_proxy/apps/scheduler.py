import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from dishka import AsyncContainer, Provider, Scope, provide
from papilio_tasks.apps.schedulers.application import create_beat, create_broker
from papilio_tasks.infra.taskiq.sources.base import Source
from taskiq.cli.scheduler.run import SchedulerLoop
from taskiq.schedule_sources import LabelScheduleSource

from papilio_proxy.modules.network.nodes.schedulers import NodeReconcileJob
from papilio_proxy.modules.network.subscriptions.schedulers import (
    ProvisionDeliveryJob,
    UsageWarningJob,
)
from papilio_proxy.modules.sales.payments.schedulers import ReceiptDecisionJob


class SharedJobsProvider(Provider):
    """Jobs reuse the bot's process-owned pool and clients, without second pools."""

    scope = Scope.APP

    def __init__(self, container: AsyncContainer) -> None:
        super().__init__()
        self._container = container

    @provide
    async def usage(self) -> UsageWarningJob:
        return await self._container.get(UsageWarningJob)

    @provide
    async def delivery(self) -> ProvisionDeliveryJob:
        return await self._container.get(ProvisionDeliveryJob)

    @provide
    async def reconcile(self) -> NodeReconcileJob:
        return await self._container.get(NodeReconcileJob)

    @provide
    async def receipts(self) -> ReceiptDecisionJob:
        return await self._container.get(ReceiptDecisionJob)


@asynccontextmanager
async def run_schedulers(container: AsyncContainer) -> AsyncIterator[None]:
    # Native Papilio Tasks discovery and Taskiq beat; durable work lives in MySQL.
    broker = create_broker(
        modules=["papilio_proxy.modules"], providers=[SharedJobsProvider(container)]
    )
    source = Source(LabelScheduleSource(broker))
    beat = create_beat(broker, sources=[source])
    await source.native.startup()
    await beat.startup()
    task = asyncio.create_task(SchedulerLoop(beat).run(skip_first_run=True))
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await beat.shutdown()
        await source.native.shutdown()
