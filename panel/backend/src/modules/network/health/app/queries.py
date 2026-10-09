from datetime import UTC, datetime, timedelta

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.network.health.domain.dtos import NodeHealthSearch
from src.modules.network.health.domain.results import NodeHealthFacts
from src.modules.network.health.infra.readers import NodeHealthReader
from src.modules.operations.automation.domain.dtos import ScheduleKey
from src.modules.operations.automation.interfaces import IAutomationPolicyQuery


class NodeHealthQuery:
    def __init__(
        self,
        reader: NodeHealthReader,
        settings: PapilioSettings,
        automation: IAutomationPolicyQuery,
    ) -> None:
        self.reader = reader
        self.settings = settings
        self.automation = automation

    async def due_ids(self) -> list[int]:
        current = await self.automation.schedule(ScheduleKey.NODES)
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
        self, data: NodeHealthSearch
    ) -> ServicePage[NodeHealthFacts]:
        limit = page_size(self.settings, data.per_page)
        result = await self.reader.page(
            data.status, data.node_id, data.q, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)
