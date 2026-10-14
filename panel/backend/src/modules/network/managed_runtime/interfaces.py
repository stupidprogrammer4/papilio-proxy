from collections.abc import Awaitable
from typing import Protocol

from src.modules.network.managed_runtime.domain.admissions import (
    ManagedAdmissionOut,
    ManagedAdmissionSubmission,
)
from src.modules.network.managed_runtime.domain.barriers import (
    ManagedWindowFinalOut,
    ManagedWindowFinalSubmission,
)
from src.modules.network.managed_runtime.domain.contracts import (
    ManagedRuntimeReadiness,
)
from src.modules.network.managed_runtime.domain.epoch_seal_models import (
    ManagedEpochSealModel,
)
from src.modules.network.managed_runtime.domain.epoch_seals import (
    ManagedEpochSealOut,
    ManagedEpochSealSubmission,
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
    ManagedRevocationModel,
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.domain.revocations import (
    ManagedRevocationOut,
    ManagedRevocationSubmission,
)
from src.modules.network.managed_runtime.domain.rollovers import (
    ManagedEpochRolloverOut,
    ManagedEpochRolloverSubmission,
    ManagedInstallationEpochCount,
)
from src.modules.network.managed_runtime.domain.successors import (
    ManagedSuccessorWindowCreate,
    ManagedSuccessorWindowOut,
)
from src.modules.network.managed_runtime.domain.windows import (
    ManagedInitialWindowCreate,
    ManagedInitialWindowOut,
)


class IManagedSuccessorWindowCommand(Protocol):
    def issue(
        self,
        code: str,
        key: str,
        predecessor_window_id: str,
        data: ManagedSuccessorWindowCreate,
    ) -> Awaitable[ManagedSuccessorWindowOut]: ...


class IManagedEpochSealCommand(Protocol):
    def accept(
        self,
        code: str,
        key: str,
        process_epoch: str,
        data: ManagedEpochSealSubmission,
    ) -> Awaitable[ManagedEpochSealOut]: ...


class IManagedFinalityCommand(Protocol):
    def finalize(
        self,
        code: str,
        key: str,
        window_id: str,
        data: ManagedWindowFinalSubmission,
    ) -> Awaitable[ManagedWindowFinalOut]: ...


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
    def locked(self, id: int) -> Awaitable[ManagedEpochModel | None]: ...
    def by_epoch(self, epoch: str) -> Awaitable[ManagedEpochModel | None]: ...
    def rollover_from(
        self, previous_epoch_id: int
    ) -> Awaitable[ManagedEpochModel | None]: ...
    def rollover_by_request(
        self, request_id: str
    ) -> Awaitable[ManagedEpochModel | None]: ...
    def count_for_installation(
        self, installation_id: int, maximum: int
    ) -> Awaitable[ManagedInstallationEpochCount]: ...


class IManagedEpochSealService(Protocol):
    def by_epoch(
        self, epoch_id: int
    ) -> Awaitable[ManagedEpochSealModel | None]: ...


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
    def rollover(
        self,
        code: str,
        key: str,
        previous_process_epoch: str,
        data: ManagedEpochRolloverSubmission,
    ) -> Awaitable[ManagedEpochRolloverOut]: ...


class IManagedWindowService(Protocol):
    def by_identity(
        self, window_id: str
    ) -> Awaitable[ManagedWindowModel | None]: ...
    def locked(self, id: int) -> Awaitable[ManagedWindowModel | None]: ...
    def by_request(
        self, profile_id: int, generation: int, request_key: str
    ) -> Awaitable[ManagedWindowModel | None]: ...
    def initial_for_profile_epoch(
        self, profile_id: int, epoch_id: int
    ) -> Awaitable[ManagedWindowModel | None]: ...
    def find(self, id: int) -> Awaitable[ManagedWindowModel | None]: ...
    def create(
        self, data: ManagedWindowModel
    ) -> Awaitable[ManagedWindowModel]: ...


class IManagedBarrierService(Protocol):
    def by_identity(
        self, epoch_id: int, barrier_id: str
    ) -> Awaitable[ManagedBarrierModel | None]: ...
    def find(self, id: int) -> Awaitable[ManagedBarrierModel | None]: ...
    def create(
        self, data: ManagedBarrierModel
    ) -> Awaitable[ManagedBarrierModel]: ...


class IManagedAdmissionService(Protocol):
    def by_window(
        self, window_id: int
    ) -> Awaitable[ManagedAdmissionModel | None]: ...
    def find(self, id: int) -> Awaitable[ManagedAdmissionModel | None]: ...
    def create(
        self, data: ManagedAdmissionModel
    ) -> Awaitable[ManagedAdmissionModel]: ...
    def by_windows_many(
        self, window_ids: list[int]
    ) -> Awaitable[list[ManagedAdmissionModel]]: ...
    def create_many(
        self, rows: list[ManagedAdmissionModel]
    ) -> Awaitable[None]: ...


class IManagedAdmissionCommand(Protocol):
    def acknowledge(
        self,
        code: str,
        key: str,
        window_id: str,
        data: ManagedAdmissionSubmission,
    ) -> Awaitable[ManagedAdmissionOut]: ...


class IManagedRevocationService(Protocol):
    def by_window(
        self, window_id: int
    ) -> Awaitable[ManagedRevocationModel | None]: ...
    def create(
        self, data: ManagedRevocationModel
    ) -> Awaitable[ManagedRevocationModel]: ...


class IManagedRevocationCommand(Protocol):
    def acknowledge(
        self,
        code: str,
        key: str,
        window_id: str,
        data: ManagedRevocationSubmission,
    ) -> Awaitable[ManagedRevocationOut]: ...


class IManagedRuntimeAuthority(Protocol):
    def readiness(self) -> ManagedRuntimeReadiness: ...
    def require_paid_activation(self) -> None: ...


class IManagedInitialWindowCommand(Protocol):
    def issue(
        self, code: str, key: str, id: int, data: ManagedInitialWindowCreate
    ) -> Awaitable[ManagedInitialWindowOut]: ...
