from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide
from papilio_tasks.infra.taskiq.sources.backends.redis import RedisSource

from src.config.settings import PapilioSettings
from src.modules.operations.automation.app.commands import (
    AutomationPolicyCommand,
    AutomationRegistrationCommand,
)
from src.modules.operations.automation.app.queries import (
    AutomationHistoryQuery,
    AutomationPolicyQuery,
)
from src.modules.operations.automation.infra.mysql import (
    AutomationRegistrationRepository,
    AutomationRevisionRepository,
)
from src.modules.operations.automation.infra.schedules import (
    RuntimeScheduleStore,
)
from src.modules.operations.automation.interfaces import (
    IAutomationHistoryQuery,
    IAutomationPolicyCommand,
    IAutomationPolicyQuery,
    IAutomationRegistrationCommand,
    IRuntimeScheduleStore,
)
from src.modules.operations.automation.tasks.schedulers.registrations import (
    ReconcileAutomationSchedule,
    ScanAutomationRegistrations,
)


class AutomationProvider(Provider):
    scope = Scope.REQUEST
    reconcile_task = provide(ReconcileAutomationSchedule)
    registration_scan_task = provide(ScanAutomationRegistrations)
    registrations = provide(AutomationRegistrationRepository)
    revisions = provide(AutomationRevisionRepository)
    policies = provide(AutomationPolicyQuery, provides=IAutomationPolicyQuery)
    changes = provide(
        AutomationPolicyCommand, provides=IAutomationPolicyCommand
    )
    history = provide(AutomationHistoryQuery, provides=IAutomationHistoryQuery)
    registration = provide(
        AutomationRegistrationCommand, provides=IAutomationRegistrationCommand
    )
    store = provide(RuntimeScheduleStore, provides=IRuntimeScheduleStore)

    @provide(scope=Scope.APP)
    async def schedule_source(
        self, settings: PapilioSettings
    ) -> AsyncIterator[RedisSource]:
        source = RedisSource(
            settings.tasks.scheduler.url,
            prefix=settings.tasks.scheduler.schedule_prefix,
        )
        try:
            yield source
        finally:
            await source.native.shutdown()
