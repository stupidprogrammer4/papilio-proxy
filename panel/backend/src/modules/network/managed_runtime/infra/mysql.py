"""Persistence only; authority decisions belong to native commands."""

from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from sqlalchemy import select
from sqlmodel import col

from src.modules.network.managed_runtime.domain.models import (
    ManagedAdmissionModel,
    ManagedBarrierModel,
    ManagedEpochModel,
    ManagedInstallationModel,
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.infra.tables import (
    ManagedAdmissionTable,
    ManagedBarrierTable,
    ManagedEpochTable,
    ManagedInstallationTable,
    ManagedWindowTable,
)


class ManagedInstallationRepository(
    MySQLPersistenceRepository[ManagedInstallationModel]
):
    table = ManagedInstallationTable

    async def by_identity(
        self, core_id: int, revision_id: int, digest: str
    ) -> ManagedInstallationModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(
                col(self.table.core_id) == core_id,
                col(self.table.runtime_revision_id) == revision_id,
                col(self.table.installation_sha256) == digest,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def locked(self, id: int) -> ManagedInstallationModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def change(
        self, row: ManagedInstallationModel, patch: ManagedInstallationModel
    ) -> ManagedInstallationModel:
        await self.update_row_by_id(row.id, patch)
        await self.uow.refresh(row)
        return row


class ManagedEpochRepository(MySQLPersistenceRepository[ManagedEpochModel]):
    table = ManagedEpochTable

    async def locked(self, id: int) -> ManagedEpochModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def by_epoch(self, epoch: str) -> ManagedEpochModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.process_epoch) == epoch)
            .with_for_update()
        )
        return result.scalar_one_or_none()


class ManagedWindowRepository(MySQLPersistenceRepository[ManagedWindowModel]):
    table = ManagedWindowTable

    async def by_identity(self, window_id: str) -> ManagedWindowModel | None:
        result = await self.uow.execute(
            select(self.table).where(col(self.table.window_id) == window_id)
        )
        return result.scalar_one_or_none()

    async def locked(self, id: int) -> ManagedWindowModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def by_request(
        self, profile_id: int, generation: int, request_key: str
    ) -> ManagedWindowModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(
                col(self.table.profile_id) == profile_id,
                col(self.table.generation) == generation,
                col(self.table.request_key) == request_key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def initial_for_profile_epoch(
        self, profile_id: int, epoch_id: int
    ) -> ManagedWindowModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(
                col(self.table.profile_id) == profile_id,
                col(self.table.epoch_id) == epoch_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()


class ManagedBarrierRepository(
    MySQLPersistenceRepository[ManagedBarrierModel]
):
    table = ManagedBarrierTable

    async def by_identity(
        self, epoch_id: int, barrier_id: str
    ) -> ManagedBarrierModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(
                col(self.table.epoch_id) == epoch_id,
                col(self.table.barrier_id) == barrier_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()


class ManagedAdmissionRepository(
    MySQLPersistenceRepository[ManagedAdmissionModel]
):
    table = ManagedAdmissionTable
