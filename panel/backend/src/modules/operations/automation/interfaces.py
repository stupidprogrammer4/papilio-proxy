from collections.abc import Awaitable
from typing import Protocol

from taskiq.decor import AsyncTaskiqDecoratedTask

from src.config.pagination import ServicePage
from src.modules.operations.automation.domain.dtos import (
    ScheduleHistorySearch,
    ScheduleKey,
    SchedulePolicy,
    ScheduleWrite,
)
from src.modules.operations.automation.domain.models import (
    AutomationRevisionModel,
)
from src.modules.operations.automation.domain.results import AutomationSchedule


class IAutomationPolicyQuery(Protocol):
    def schedule(self, key: ScheduleKey) -> Awaitable[AutomationSchedule]: ...
    def schedules(self) -> Awaitable[list[AutomationSchedule]]: ...


class IAutomationPolicyCommand(Protocol):
    def write(
        self, key: ScheduleKey, data: ScheduleWrite, staff_id: int
    ) -> Awaitable[AutomationSchedule]: ...


class IAutomationHistoryQuery(Protocol):
    def search(
        self, key: ScheduleKey, data: ScheduleHistorySearch
    ) -> Awaitable[ServicePage[AutomationRevisionModel]]: ...


class IAutomationRegistrationCommand(Protocol):
    def reconcile(
        self, key: ScheduleKey, task: AsyncTaskiqDecoratedTask
    ) -> Awaitable[int]: ...


class IRuntimeScheduleStore(Protocol):
    def reconcile(
        self,
        key: ScheduleKey,
        task: AsyncTaskiqDecoratedTask,
        policy: SchedulePolicy,
        revision: int,
    ) -> Awaitable[None]: ...
