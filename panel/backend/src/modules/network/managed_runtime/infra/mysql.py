"""Persistence only; authority decisions belong to native commands."""

from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)

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


class ManagedEpochRepository(MySQLPersistenceRepository[ManagedEpochModel]):
    table = ManagedEpochTable


class ManagedWindowRepository(MySQLPersistenceRepository[ManagedWindowModel]):
    table = ManagedWindowTable


class ManagedBarrierRepository(
    MySQLPersistenceRepository[ManagedBarrierModel]
):
    table = ManagedBarrierTable


class ManagedAdmissionRepository(
    MySQLPersistenceRepository[ManagedAdmissionModel]
):
    table = ManagedAdmissionTable
