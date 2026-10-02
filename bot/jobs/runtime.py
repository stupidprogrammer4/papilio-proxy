from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from aiogram import Bot
from dishka import Provider
from papilio_tasks.apps.schedulers import Registrar
from papilio_tasks.apps.schedulers.application import create_beat, create_broker
from papilio_tasks.infra.taskiq.sources.base import Source
from taskiq.cli.scheduler.run import SchedulerLoop
from taskiq.schedule_sources import LabelScheduleSource

from bot.infra.db.access import MysqlAccessRepository
from bot.jobs.schedulers import (
    NodeReconcileJob,
    NodeReconcileProvider,
    ProvisionDeliveryDispatcher,
    ProvisionDeliveryJob,
    ProvisionDeliveryProvider,
    UsageWarningDispatcher,
    UsageWarningJob,
    UsageWarningProvider,
)
from bot.services.node import NodeReconciler


@asynccontextmanager
async def usage_warning_scheduler(
    repository: MysqlAccessRepository, bot: Bot, reconciler: NodeReconciler | None = None,
    public_base: str | None = None,
) -> AsyncIterator[None]:
    """One-process Papilio Tasks beat; MySQL outbox survives its restarts."""
    dispatcher = UsageWarningDispatcher(repository, bot)
    registrar = Registrar()
    registrar.include(UsageWarningJob)
    providers: list[Provider] = [UsageWarningProvider(dispatcher)]
    if reconciler is not None:
        registrar.include(NodeReconcileJob)
        providers.append(NodeReconcileProvider(reconciler))
    if public_base is not None:
        registrar.include(ProvisionDeliveryJob)
        providers.append(ProvisionDeliveryProvider(
            ProvisionDeliveryDispatcher(repository, bot, public_base, reconciler.access if reconciler else None)
        ))
    broker = create_broker(registrar=registrar, providers=providers)
    source = Source(LabelScheduleSource(broker))
    beat = create_beat(broker, sources=[source])
    await source.native.startup()
    await beat.startup()
    loop_task = asyncio.create_task(SchedulerLoop(beat).run(skip_first_run=True))
    try:
        yield
    finally:
        loop_task.cancel()
        with suppress(asyncio.CancelledError):
            await loop_task
        await beat.shutdown()
        await source.native.shutdown()
