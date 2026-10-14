"""Repository-backed batch capabilities for managed provision leases."""

from src.modules.network.provisioning.domain.models import (
    ProvisionRequestModel,
    ProvisionTaskModel,
)
from src.modules.network.provisioning.domain.results import (
    ProvisionGenerationKey,
)
from src.modules.network.provisioning.infra.mysql import (
    ProvisionRequestRepository,
    ProvisionTaskRepository,
)


class ProvisionRequestBatchService:
    def __init__(self, repo: ProvisionRequestRepository) -> None:
        self.repo = repo

    async def by_generations(
        self, keys: list[ProvisionGenerationKey]
    ) -> list[ProvisionRequestModel]:
        result = await self.repo.by_generations(keys)
        return result


class ProvisionTaskBatchService:
    def __init__(self, repo: ProvisionTaskRepository) -> None:
        self.repo = repo

    async def locked_many(self, ids: list[int]) -> list[ProvisionTaskModel]:
        result = await self.repo.locked_many(ids)
        return result

    async def change_many(self, rows: list[ProvisionTaskModel]) -> None:
        await self.repo.change_many(rows)
