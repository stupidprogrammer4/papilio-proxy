from datetime import UTC, datetime, timedelta

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.operations.automation.domain.dtos import ScheduleKey
from src.modules.operations.automation.interfaces import IAutomationPolicyQuery
from src.modules.sales.attention.domain.dtos import SubscriptionAttentionSearch
from src.modules.sales.attention.domain.results import (
    SubscriptionAttentionFacts,
)
from src.modules.sales.attention.infra.readers import (
    SubscriptionAttentionReader,
)


class SubscriptionAttentionQuery:
    def __init__(
        self,
        reader: SubscriptionAttentionReader,
        settings: PapilioSettings,
        automation: IAutomationPolicyQuery,
    ) -> None:
        self.reader = reader
        self.settings = settings
        self.automation = automation

    async def due_ids(self) -> list[int]:
        current = await self.automation.schedule(ScheduleKey.ATTENTION)
        if not current.runnable:
            return []
        schedule = current.values
        assert schedule.recheck_seconds is not None
        before = datetime.now(UTC).replace(tzinfo=None) - timedelta(
            seconds=schedule.recheck_seconds
        )
        result = await self.reader.due_ids(before, schedule.batch_size)
        return result

    async def search(
        self, data: SubscriptionAttentionSearch
    ) -> ServicePage[SubscriptionAttentionFacts]:
        limit = page_size(self.settings, data.per_page)
        result = await self.reader.page(
            data.status,
            data.customer_id,
            data.q,
            (data.page - 1) * limit,
            limit,
        )
        return service_page(result, limit)
