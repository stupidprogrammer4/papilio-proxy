from collections.abc import Awaitable
from typing import Protocol

from src.modules.network.managed_runtime.domain.contracts import (
    ManagedRuntimeReadiness,
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


class IManagedEpochService(Protocol):
    def find(self, id: int) -> Awaitable[ManagedEpochModel | None]: ...
    def create(
        self, data: ManagedEpochModel
    ) -> Awaitable[ManagedEpochModel]: ...


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
