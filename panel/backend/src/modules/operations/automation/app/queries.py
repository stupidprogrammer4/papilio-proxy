from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.operations.automation.app.defaults import AutomationDefaults
from src.modules.operations.automation.domain.dtos import (
    ScheduleHistorySearch,
    ScheduleKey,
)
from src.modules.operations.automation.domain.models import (
    AutomationRevisionModel,
)
from src.modules.operations.automation.domain.results import AutomationSchedule
from src.modules.operations.automation.infra.mysql import (
    AutomationRegistrationRepository,
    AutomationRevisionRepository,
)


class AutomationPolicyQuery:
    def __init__(
        self, repo: AutomationRegistrationRepository, settings: PapilioSettings
    ) -> None:
        self.repo = repo
        self.defaults = AutomationDefaults(settings)

    async def schedule(self, key: ScheduleKey) -> AutomationSchedule:
        row = await self.repo.by_key(key.value)
        return self.defaults.registration_view(key, row)

    async def schedules(self) -> list[AutomationSchedule]:
        rows = await self.repo.configured([key.value for key in ScheduleKey])
        indexed = {row.key: row for row in rows}
        return [
            self.defaults.registration_view(key, indexed.get(key))
            for key in ScheduleKey
        ]


class AutomationHistoryQuery:
    def __init__(
        self, repo: AutomationRevisionRepository, settings: PapilioSettings
    ) -> None:
        self.repo = repo
        self.settings = settings

    async def search(
        self, key: ScheduleKey, data: ScheduleHistorySearch
    ) -> ServicePage[AutomationRevisionModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(
            key.value, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)
