from src.modules.network.managed_runtime.domain.models import (
    ManagedAdmissionModel,
    ManagedBarrierModel,
    ManagedEpochModel,
    ManagedInstallationModel,
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.infra.mysql import (
    ManagedAdmissionRepository,
    ManagedBarrierRepository,
    ManagedEpochRepository,
    ManagedInstallationRepository,
    ManagedWindowRepository,
)


class ManagedInstallationService:
    def __init__(self, repo: ManagedInstallationRepository) -> None:
        self.repo = repo

    async def find(self, id: int) -> ManagedInstallationModel | None:
        result = await self.repo.get_by_id(id)
        return result

    async def create(
        self, data: ManagedInstallationModel
    ) -> ManagedInstallationModel:
        result = await self.repo.create(data)
        return result


class ManagedEpochService:
    def __init__(self, repo: ManagedEpochRepository) -> None:
        self.repo = repo

    async def find(self, id: int) -> ManagedEpochModel | None:
        result = await self.repo.get_by_id(id)
        return result

    async def create(self, data: ManagedEpochModel) -> ManagedEpochModel:
        result = await self.repo.create(data)
        return result


class ManagedWindowService:
    def __init__(self, repo: ManagedWindowRepository) -> None:
        self.repo = repo

    async def find(self, id: int) -> ManagedWindowModel | None:
        result = await self.repo.get_by_id(id)
        return result

    async def create(self, data: ManagedWindowModel) -> ManagedWindowModel:
        result = await self.repo.create(data)
        return result


class ManagedBarrierService:
    def __init__(self, repo: ManagedBarrierRepository) -> None:
        self.repo = repo

    async def find(self, id: int) -> ManagedBarrierModel | None:
        result = await self.repo.get_by_id(id)
        return result

    async def create(self, data: ManagedBarrierModel) -> ManagedBarrierModel:
        result = await self.repo.create(data)
        return result


class ManagedAdmissionService:
    def __init__(self, repo: ManagedAdmissionRepository) -> None:
        self.repo = repo

    async def find(self, id: int) -> ManagedAdmissionModel | None:
        result = await self.repo.get_by_id(id)
        return result

    async def create(
        self, data: ManagedAdmissionModel
    ) -> ManagedAdmissionModel:
        result = await self.repo.create(data)
        return result
