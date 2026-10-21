"""Owner-only configuration of known native Beat schedules."""

from django.db import transaction

from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.shared.errors import InvalidInput

from ..domain import ScheduleRead, ScheduleUpdate
from ..interfaces import ScheduleStorage


class ManagedSchedules:
    def __init__(self, storage: ScheduleStorage, access: AdminAccessCapability) -> None:
        self.storage = storage
        self.access = access

    def read_all(self, actor_id: int) -> tuple[ScheduleRead, ...]:
        self.access.authorize_owner(actor_id)
        schedules = self.storage.read_all()
        return schedules

    @transaction.atomic
    def update(self, actor_id: int, values: ScheduleUpdate) -> ScheduleRead:
        self.access.authorize_owner(actor_id)
        if not 1 <= values.interval_seconds <= 2147483647:
            raise InvalidInput("The interval must fit a positive PostgreSQL integer.")
        schedule = self.storage.update(values)
        return schedule
