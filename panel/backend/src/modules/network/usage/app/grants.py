"""Repository-backed usage grant operations for single and batch callers."""

from src.modules.network.usage.domain.models import UsageGrantModel
from src.modules.network.usage.domain.results import UsageGrantAllocationKey
from src.modules.network.usage.infra.mysql import UsageGrantRepository


class UsageGrantService:
    def __init__(self, repo: UsageGrantRepository) -> None:
        self.repo = repo

    async def locked(self, id: int) -> UsageGrantModel | None:
        result = await self.repo.locked(id)
        return result

    async def locked_many(self, ids: list[int]) -> list[UsageGrantModel]:
        result = await self.repo.locked_many(ids)
        return result

    async def allocation_many(
        self, keys: list[UsageGrantAllocationKey]
    ) -> list[UsageGrantModel]:
        result = await self.repo.allocations_many(keys)
        return result

    async def create(self, data: UsageGrantModel) -> UsageGrantModel:
        result = await self.repo.create(data)
        return result

    async def create_many(self, rows: list[UsageGrantModel]) -> None:
        await self.repo.create_many(rows)

    async def change(
        self, row: UsageGrantModel, changes: UsageGrantModel
    ) -> UsageGrantModel:
        result = await self.repo.change(row, changes)
        return result

    async def change_many(
        self, rows: list[UsageGrantModel]
    ) -> list[UsageGrantModel]:
        result = await self.repo.change_many(rows)
        return result
