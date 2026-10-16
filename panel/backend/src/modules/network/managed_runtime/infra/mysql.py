"""Persistence only; authority decisions belong to native commands."""

from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from sqlalchemy import select, tuple_
from sqlmodel import col

from src.modules.network.managed_runtime.domain.models import (
    ManagedAdmissionModel,
    ManagedBarrierModel,
    ManagedEpochModel,
    ManagedInstallationModel,
    ManagedOperationBatchModel,
    ManagedRevocationModel,
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.domain.results import (
    ManagedBarrierIdentity,
    ManagedWindowRequestIdentity,
)
from src.modules.network.managed_runtime.domain.rollovers import (
    ManagedInstallationEpochCount,
)
from src.modules.network.managed_runtime.infra.tables import (
    ManagedAdmissionTable,
    ManagedBarrierTable,
    ManagedEpochTable,
    ManagedInstallationTable,
    ManagedOperationBatchTable,
    ManagedRevocationTable,
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

    async def count_for_installation(
        self, installation_id: int, maximum: int
    ) -> ManagedInstallationEpochCount:
        result = await self.uow.execute(
            select(col(self.table.id))
            .where(col(self.table.installation_id) == installation_id)
            .order_by(col(self.table.id))
            .limit(maximum + 1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        epoch_ids = tuple(result.scalars())
        return ManagedInstallationEpochCount(
            installation_id=installation_id,
            observed_count=len(epoch_ids),
            count_capped=len(epoch_ids) > maximum,
        )

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

    async def rollover_from(
        self, previous_epoch_id: int
    ) -> ManagedEpochModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.previous_epoch_id) == previous_epoch_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def rollover_by_request(
        self, request_id: str
    ) -> ManagedEpochModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.rollover_request_id) == request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()


class ManagedOperationBatchRepository(
    MySQLPersistenceRepository[ManagedOperationBatchModel]
):
    table = ManagedOperationBatchTable

    async def by_identity(
        self, installation_id: int, operation: str, request_key: str
    ) -> ManagedOperationBatchModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(
                col(self.table.installation_id) == installation_id,
                col(self.table.operation) == operation,
                col(self.table.request_key) == request_key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
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
                col(self.table.predecessor_id).is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def initials_for_profiles_epoch(
        self, profile_ids: list[int], epoch_id: int
    ) -> list[ManagedWindowModel]:
        selected = sorted(set(profile_ids))
        if not selected:
            return []
        result = await self.uow.execute(
            select(self.table)
            .where(
                col(self.table.profile_id).in_(selected),
                col(self.table.epoch_id) == epoch_id,
                col(self.table.predecessor_id).is_(None),
            )
            .order_by(col(self.table.profile_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def by_operation_batch(
        self, operation_batch_id: int
    ) -> list[ManagedWindowModel]:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.operation_batch_id) == operation_batch_id)
            .order_by(col(self.table.profile_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def by_identities_many(
        self, window_ids: list[str]
    ) -> list[ManagedWindowModel]:
        selected = sorted(set(window_ids))
        if not selected:
            return []
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.window_id).in_(selected))
            .order_by(col(self.table.id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def find_by_identities_many(
        self, window_ids: list[str]
    ) -> list[ManagedWindowModel]:
        selected = sorted(set(window_ids))
        if not selected:
            return []
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.window_id).in_(selected))
            .order_by(col(self.table.id))
        )
        return list(result.scalars().all())

    async def by_requests_many(
        self, identities: list[ManagedWindowRequestIdentity]
    ) -> list[ManagedWindowModel]:
        if not identities:
            return []
        result = await self.uow.execute(
            select(self.table)
            .where(
                tuple_(
                    col(self.table.profile_id),
                    col(self.table.generation),
                    col(self.table.request_key),
                ).in_(
                    [
                        (item.profile_id, item.generation, item.request_key)
                        for item in identities
                    ]
                )
            )
            .order_by(col(self.table.profile_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def create_many(self, rows: list[ManagedWindowModel]) -> None:
        columns = {
            name: ManagedWindowTable.__table__.c[name]
            for name in (
                "operation_batch_id",
                "encrypted_provision_claim",
                "epoch_id",
                "grant_id",
                "profile_id",
                "subscription_id",
                "provision_task_id",
                "generation",
                "window_id",
                "request_key",
                "request_sha256",
                "window_sha256",
                "baseline_upload_bytes",
                "baseline_download_bytes",
                "allocated_bytes",
                "issued_at",
                "valid_until",
                "predecessor_id",
                "encrypted_window",
            )
        }
        await self.bulk_insert(rows, insert_columns=columns)


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

    async def by_identities_many(
        self, identities: list[ManagedBarrierIdentity]
    ) -> list[ManagedBarrierModel]:
        if not identities:
            return []
        result = await self.uow.execute(
            select(self.table)
            .where(
                tuple_(
                    col(self.table.epoch_id), col(self.table.barrier_id)
                ).in_(
                    [(item.epoch_id, item.barrier_id) for item in identities]
                )
            )
            .order_by(col(self.table.id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def create_many(self, rows: list[ManagedBarrierModel]) -> None:
        columns = {
            name: ManagedBarrierTable.__table__.c[name]
            for name in (
                "epoch_id",
                "barrier_id",
                "acceptance_id",
                "snapshot_sha256",
                "request_sha256",
                "frozen_at",
                "accepted_at",
                "encrypted_receipt",
            )
        }
        await self.bulk_insert(rows, insert_columns=columns)


class ManagedAdmissionRepository(
    MySQLPersistenceRepository[ManagedAdmissionModel]
):
    table = ManagedAdmissionTable

    async def by_window(self, window_id: int) -> ManagedAdmissionModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.window_id) == window_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def by_windows_many(
        self, window_ids: list[int]
    ) -> list[ManagedAdmissionModel]:
        selected = sorted(set(window_ids))
        if not selected:
            return []
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.window_id).in_(selected))
            .order_by(col(self.table.window_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def create_many(self, rows: list[ManagedAdmissionModel]) -> None:
        if not rows:
            return
        columns = {
            name: ManagedAdmissionTable.__table__.c[name]
            for name in (
                "window_id",
                "provision_task_id",
                "receipt_sha256",
                "outcome",
                "observed_at",
                "encrypted_receipt",
            )
        }
        await self.bulk_insert(rows, insert_columns=columns)


class ManagedRevocationRepository(
    MySQLPersistenceRepository[ManagedRevocationModel]
):
    table = ManagedRevocationTable

    async def by_window(self, window_id: int) -> ManagedRevocationModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.window_id) == window_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()
