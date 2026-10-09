from dataclasses import dataclass
from datetime import datetime

from src.modules.operations.automation.domain.dtos import (
    ScheduleKey,
    SchedulePolicy,
)


@dataclass(frozen=True, slots=True)
class AutomationSchedule:
    key: ScheduleKey
    scope: str
    values: SchedulePolicy
    revision: int
    applied_revision: int | None
    registered_at: datetime | None
    capacity_valid: bool

    @property
    def runnable(self) -> bool:
        return self.values.enabled and self.capacity_valid
