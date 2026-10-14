from papilio.errors.exceptions import NotFoundException

from src.modules.network.managed_runtime.domain.epoch_seal_models import (
    ManagedEpochSealModel,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedAdmissionModel,
    ManagedBarrierModel,
    ManagedEpochModel,
    ManagedInstallationModel,
    ManagedRevocationModel,
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.domain.rollovers import (
    ManagedInstallationEpochCount,
)
from src.modules.network.managed_runtime.infra.epoch_seal_mysql import (
    ManagedEpochSealRepository,
)
from src.modules.network.managed_runtime.infra.mysql import (
    ManagedAdmissionRepository,
    ManagedBarrierRepository,
    ManagedEpochRepository,
    ManagedInstallationRepository,
    ManagedRevocationRepository,
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

    async def locked(self, id: int) -> ManagedInstallationModel:
        result = await self.repo.locked(id)
        if result is None:
            raise NotFoundException(
                message="Managed installation not found.",
                message_code="managed_installation_missing",
                entity="managed_installation",
                identifier="id",
                identifier_value=id,
            )
        return result

    async def by_identity(
        self, core_id: int, revision_id: int, digest: str
    ) -> ManagedInstallationModel | None:
        result = await self.repo.by_identity(core_id, revision_id, digest)
        return result

    async def change(
        self, row: ManagedInstallationModel, patch: ManagedInstallationModel
    ) -> ManagedInstallationModel:
        result = await self.repo.change(row, patch)
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

    async def locked(self, id: int) -> ManagedEpochModel | None:
        result = await self.repo.locked(id)
        return result

    async def by_epoch(self, epoch: str) -> ManagedEpochModel | None:
        result = await self.repo.by_epoch(epoch)
        return result

    async def rollover_from(
        self, previous_epoch_id: int
    ) -> ManagedEpochModel | None:
        result = await self.repo.rollover_from(previous_epoch_id)
        return result

    async def rollover_by_request(
        self, request_id: str
    ) -> ManagedEpochModel | None:
        result = await self.repo.rollover_by_request(request_id)
        return result

    async def count_for_installation(
        self, installation_id: int, maximum: int
    ) -> ManagedInstallationEpochCount:
        result = await self.repo.count_for_installation(
            installation_id, maximum
        )
        return result


class ManagedEpochSealService:
    def __init__(self, repo: ManagedEpochSealRepository) -> None:
        self.repo = repo

    async def by_epoch(self, epoch_id: int) -> ManagedEpochSealModel | None:
        result = await self.repo.by_epoch(epoch_id)
        return result


class ManagedWindowService:
    def __init__(self, repo: ManagedWindowRepository) -> None:
        self.repo = repo

    async def find(self, id: int) -> ManagedWindowModel | None:
        result = await self.repo.get_by_id(id)
        return result

    async def by_identity(self, window_id: str) -> ManagedWindowModel | None:
        result = await self.repo.by_identity(window_id)
        return result

    async def locked(self, id: int) -> ManagedWindowModel | None:
        result = await self.repo.locked(id)
        return result

    async def by_request(
        self, profile_id: int, generation: int, request_key: str
    ) -> ManagedWindowModel | None:
        result = await self.repo.by_request(
            profile_id, generation, request_key
        )
        return result

    async def initial_for_profile_epoch(
        self, profile_id: int, epoch_id: int
    ) -> ManagedWindowModel | None:
        result = await self.repo.initial_for_profile_epoch(
            profile_id, epoch_id
        )
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

    async def by_identity(
        self, epoch_id: int, barrier_id: str
    ) -> ManagedBarrierModel | None:
        result = await self.repo.by_identity(epoch_id, barrier_id)
        return result

    async def create(self, data: ManagedBarrierModel) -> ManagedBarrierModel:
        result = await self.repo.create(data)
        return result


class ManagedAdmissionService:
    def __init__(self, repo: ManagedAdmissionRepository) -> None:
        self.repo = repo

    async def by_window(self, window_id: int) -> ManagedAdmissionModel | None:
        result = await self.repo.by_window(window_id)
        return result

    async def find(self, id: int) -> ManagedAdmissionModel | None:
        result = await self.repo.get_by_id(id)
        return result

    async def create(
        self, data: ManagedAdmissionModel
    ) -> ManagedAdmissionModel:
        result = await self.repo.create(data)
        return result


class ManagedRevocationService:
    def __init__(self, repo: ManagedRevocationRepository) -> None:
        self.repo = repo

    async def by_window(self, window_id: int) -> ManagedRevocationModel | None:
        result = await self.repo.by_window(window_id)
        return result

    async def create(
        self, data: ManagedRevocationModel
    ) -> ManagedRevocationModel:
        result = await self.repo.create(data)
        return result
