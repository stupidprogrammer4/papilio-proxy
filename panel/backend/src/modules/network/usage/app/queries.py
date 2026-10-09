from datetime import UTC

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.network.usage.domain.dtos import UsageSearch
from src.modules.network.usage.domain.models import (
    UsageEventModel,
    UsageGrantModel,
)
from src.modules.network.usage.domain.results import UsageSummary
from src.modules.network.usage.infra.mysql import UsageGrantRepository
from src.modules.network.usage.infra.readers import UsageFactsReader


class UsageQuery:
    def __init__(
        self,
        repo: UsageGrantRepository,
        facts: UsageFactsReader,
        settings: PapilioSettings,
    ) -> None:
        self.repo = repo
        self.facts = facts
        self.settings = settings

    async def grants(self, data: UsageSearch) -> ServicePage[UsageGrantModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(
            data.subscription_id,
            data.node_id,
            data.generation,
            (data.page - 1) * limit,
            limit,
        )
        return service_page(result, limit)

    async def events(self, data: UsageSearch) -> ServicePage[UsageEventModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.facts.events(
            data.subscription_id,
            data.node_id,
            data.generation,
            data.since.astimezone(UTC).replace(tzinfo=None)
            if data.since
            else None,
            data.until.astimezone(UTC).replace(tzinfo=None)
            if data.until
            else None,
            (data.page - 1) * limit,
            limit,
        )
        return service_page(result, limit)

    async def summary(self, data: UsageSearch) -> UsageSummary:
        result = await self.facts.summary(
            data.subscription_id,
            data.node_id,
            data.generation,
            data.since.astimezone(UTC).replace(tzinfo=None)
            if data.since
            else None,
            data.until.astimezone(UTC).replace(tzinfo=None)
            if data.until
            else None,
        )
        return result

    async def has_open_profile(self, profile_id: int, generation: int) -> bool:
        result = await self.facts.has_open_profile(profile_id, generation)
        return result
