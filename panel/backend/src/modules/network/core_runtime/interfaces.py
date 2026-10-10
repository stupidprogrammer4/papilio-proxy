from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.network.core_runtime.domain.dtos import (
    RuntimeAcknowledgement,
    RuntimeClaim,
    RuntimeCommandCreate,
    RuntimeRevisionCreate,
    RuntimeSearch,
)
from src.modules.network.core_runtime.domain.memberships import (
    CoreProvisioningDecision,
    InstalledProfileProof,
    RuntimeProvisioningBudget,
)
from src.modules.network.core_runtime.domain.models import (
    CoreRuntimeCommandModel,
    CoreRuntimeRevisionModel,
    CoreRuntimeStateModel,
)
from src.modules.network.core_runtime.domain.results import (
    RuntimeRevisionOut,
    RuntimeStateOut,
    RuntimeUsageObservationOut,
)
from src.modules.network.core_runtime.domain.usage import (
    RuntimeUsageCapability,
    RuntimeUsageObservation,
)


class ICoreUsageObservationCommand(Protocol):
    def observe(
        self, code: str, key: str, core_id: int, data: RuntimeUsageObservation
    ) -> Awaitable[RuntimeUsageObservationOut]: ...


class ICoreUsagePolicyQuery(Protocol):
    def admission(
        self, core_id: int, node_id: int, kind: str, current: bool = True
    ) -> Awaitable[str | None]: ...
    def capability(
        self, core_id: int, node_id: int, kind: str, current: bool = False
    ) -> Awaitable[RuntimeUsageCapability]: ...


class IInstalledUsageQuery(Protocol):
    def required(self, core_id: int) -> bool: ...
    def lock_core(self, core_id: int) -> Awaitable[None]: ...
    def allocation_guard(self, core_id: int) -> Awaitable[None]: ...
    def proof(
        self,
        core_id: int,
        node_id: int,
        profile_id: int,
        subscription_id: int,
        generation: int,
        configuration_revision: int,
        revision_id: int,
        usage_sha256: str,
        process_epoch: str,
    ) -> Awaitable[None]: ...


class ICoreProvisioningBudgetQuery(Protocol):
    def current(
        self, core_id: int, revision_id: int
    ) -> Awaitable[RuntimeProvisioningBudget]: ...


class IRuntimeStateService(Protocol):
    def lock_nodes_for_cores(self, core_ids: list[int]) -> Awaitable[None]: ...
    def lock_core(self, core_id: int) -> Awaitable[None]: ...
    def lock_cores(self, core_ids: list[int]) -> Awaitable[None]: ...
    def current(
        self, core_id: int
    ) -> Awaitable[CoreRuntimeStateModel | None]: ...
    def find(
        self, core_id: int
    ) -> Awaitable[CoreRuntimeStateModel | None]: ...
    def locked(self, core_id: int) -> Awaitable[CoreRuntimeStateModel]: ...
    def change(
        self, row: CoreRuntimeStateModel, patch: CoreRuntimeStateModel
    ) -> Awaitable[CoreRuntimeStateModel]: ...


class IRuntimeRevisionService(Protocol):
    def create(
        self, row: CoreRuntimeRevisionModel
    ) -> Awaitable[CoreRuntimeRevisionModel]: ...
    def get(
        self, id: int, core_id: int
    ) -> Awaitable[CoreRuntimeRevisionModel]: ...


class IRuntimeCommandService(Protocol):
    def locked_get(self, id: int) -> Awaitable[CoreRuntimeCommandModel]: ...
    def actionable(
        self, node_id: int, data: RuntimeSearch
    ) -> Awaitable[ServicePage[CoreRuntimeCommandModel]]: ...
    def create(
        self, row: CoreRuntimeCommandModel
    ) -> Awaitable[CoreRuntimeCommandModel]: ...
    def get(self, id: int) -> Awaitable[CoreRuntimeCommandModel]: ...
    def by_key(
        self, core_id: int, key: str
    ) -> Awaitable[CoreRuntimeCommandModel | None]: ...
    def outstanding(
        self, core_id: int
    ) -> Awaitable[CoreRuntimeCommandModel | None]: ...
    def change(
        self, row: CoreRuntimeCommandModel, patch: CoreRuntimeCommandModel
    ) -> Awaitable[CoreRuntimeCommandModel]: ...
    def search(
        self, core_id: int | None, node_id: int | None, data: RuntimeSearch
    ) -> Awaitable[ServicePage[CoreRuntimeCommandModel]]: ...


class ICoreRuntimeQuery(Protocol):
    def state(self, core_id: int) -> Awaitable[RuntimeStateOut]: ...
    def revisions(
        self, core_id: int, data: RuntimeSearch
    ) -> Awaitable[ServicePage[RuntimeRevisionOut]]: ...
    def commands(
        self, core_id: int, data: RuntimeSearch
    ) -> Awaitable[ServicePage[CoreRuntimeCommandModel]]: ...
    def node_commands(
        self, code: str, key: str, data: RuntimeSearch
    ) -> Awaitable[ServicePage[CoreRuntimeCommandModel]]: ...
    def due_command_ids(
        self, limit: int | None = None
    ) -> Awaitable[list[int]]: ...


class ICoreRuntimeCommand(Protocol):
    def revision(
        self,
        core_id: int,
        data: RuntimeRevisionCreate,
        staff_id: int | None = None,
    ) -> Awaitable[CoreRuntimeRevisionModel]: ...
    def enqueue(
        self,
        core_id: int,
        data: RuntimeCommandCreate,
        staff_id: int | None = None,
        purpose: str = "operator",
    ) -> Awaitable[CoreRuntimeCommandModel]: ...
    def claim(
        self, code: str, key: str, command_id: int
    ) -> Awaitable[RuntimeClaim]: ...
    def acknowledge(
        self,
        code: str,
        key: str,
        command_id: int,
        data: RuntimeAcknowledgement,
    ) -> Awaitable[CoreRuntimeCommandModel]: ...
    def recover(
        self, command_id: int
    ) -> Awaitable[CoreRuntimeCommandModel]: ...


class ICoreProvisioningQuery(Protocol):
    def due_core_ids(
        self, limit: int | None = None
    ) -> Awaitable[list[int]]: ...


class ICoreProvisioningCommand(Protocol):
    def ensure(self, core_id: int) -> Awaitable[CoreProvisioningDecision]: ...


class IInstalledProfileQuery(Protocol):
    def matches_current(
        self, core_id: int, revision_id: int
    ) -> Awaitable[bool]: ...
    def lock_core(self, core_id: int) -> Awaitable[None]: ...
    def lock_cores(self, core_ids: list[int]) -> Awaitable[None]: ...
    def proof(
        self,
        core_id: int,
        profile_id: int,
        generation: int,
        configuration_revision: int,
        action: str,
        credential_sha256: str,
    ) -> Awaitable[InstalledProfileProof]: ...
