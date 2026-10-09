from collections.abc import Awaitable
from typing import Protocol

from src.modules.network.managed_runtime.domain.contracts import (
    ManagedRuntimeReadiness,
)
from src.modules.network.managed_runtime.domain.installations import (
    ManagedClosedStartupAcknowledgement,
    ManagedInstallationClaim,
    ManagedInstallationCreate,
    ManagedInstalledClosedOut,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedAdmissionModel,
    ManagedBarrierModel,
    ManagedEpochModel,
    ManagedInstallationModel,
    ManagedWindowModel,
)


class IManagedInstallationService(Protocol):
    def find(self, id: int) -> Awaitable[ManagedInstallationModel | None]: ...
    def create(
        self, data: ManagedInstallationModel
    ) -> Awaitable[ManagedInstallationModel]: ...
    def locked(self, id: int) -> Awaitable[ManagedInstallationModel]: ...
    def by_identity(
        self, core_id: int, revision_id: int, digest: str
    ) -> Awaitable[ManagedInstallationModel | None]: ...
    def change(
        self, row: ManagedInstallationModel, patch: ManagedInstallationModel
    ) -> Awaitable[ManagedInstallationModel]: ...


class IManagedEpochService(Protocol):
    def find(self, id: int) -> Awaitable[ManagedEpochModel | None]: ...
    def create(
        self, data: ManagedEpochModel
    ) -> Awaitable[ManagedEpochModel]: ...
    def by_epoch(self, epoch: str) -> Awaitable[ManagedEpochModel | None]: ...


class IManagedInstallationCommand(Protocol):
    def issue(
        self, core_id: int, data: ManagedInstallationCreate
    ) -> Awaitable[ManagedInstallationModel]: ...
    def claim(
        self, code: str, key: str, id: int
    ) -> Awaitable[ManagedInstallationClaim]: ...
    def acknowledge(
        self,
        code: str,
        key: str,
        id: int,
        data: ManagedClosedStartupAcknowledgement,
    ) -> Awaitable[ManagedInstalledClosedOut]: ...


class IManagedWindowService(Protocol):
    def find(self, id: int) -> Awaitable[ManagedWindowModel | None]: ...
    def create(
        self, data: ManagedWindowModel
    ) -> Awaitable[ManagedWindowModel]: ...


class IManagedBarrierService(Protocol):
    def find(self, id: int) -> Awaitable[ManagedBarrierModel | None]: ...
    def create(
        self, data: ManagedBarrierModel
    ) -> Awaitable[ManagedBarrierModel]: ...


class IManagedAdmissionService(Protocol):
    def find(self, id: int) -> Awaitable[ManagedAdmissionModel | None]: ...
    def create(
        self, data: ManagedAdmissionModel
    ) -> Awaitable[ManagedAdmissionModel]: ...


class IManagedRuntimeAuthority(Protocol):
    def readiness(self) -> ManagedRuntimeReadiness: ...
    def require_paid_activation(self) -> None: ...
