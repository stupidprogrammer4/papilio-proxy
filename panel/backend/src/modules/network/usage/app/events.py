"""Repository-backed batch persistence for usage events."""

from src.modules.network.usage.domain.models import UsageEventModel
from src.modules.network.usage.domain.results import UsageEventIdentity
from src.modules.network.usage.infra.mysql import UsageEventRepository


class UsageEventService:
    def __init__(self, repo: UsageEventRepository) -> None:
        self.repo = repo

    async def create_many(self, rows: list[UsageEventModel]) -> None:
        await self.repo.create_many(rows)

    async def by_identities_many(
        self, identities: list[UsageEventIdentity]
    ) -> list[UsageEventModel]:
        result = await self.repo.by_identities_many(identities)
        return result
