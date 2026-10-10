from dishka import Provider, Scope, provide

from src.modules.network.managed_runtime.app.admissions import (
    ManagedAdmissionCommand,
)
from src.modules.network.managed_runtime.app.authority import (
    ManagedRuntimeAuthority,
)
from src.modules.network.managed_runtime.app.barriers import (
    ManagedFinalityCommand,
)
from src.modules.network.managed_runtime.app.installations import (
    ManagedInstallationCommand,
)
from src.modules.network.managed_runtime.app.revocations import (
    ManagedRevocationCommand,
)
from src.modules.network.managed_runtime.app.services import (
    ManagedAdmissionService,
    ManagedBarrierService,
    ManagedEpochService,
    ManagedInstallationService,
    ManagedRevocationService,
    ManagedWindowService,
)
from src.modules.network.managed_runtime.app.successors import (
    ManagedSuccessorWindowCommand,
)
from src.modules.network.managed_runtime.app.windows import (
    ManagedInitialWindowCommand,
)
from src.modules.network.managed_runtime.infra.mysql import (
    ManagedAdmissionRepository,
    ManagedBarrierRepository,
    ManagedEpochRepository,
    ManagedInstallationRepository,
    ManagedRevocationRepository,
    ManagedWindowRepository,
)
from src.modules.network.managed_runtime.infra.scopes import (
    ManagedInstallationScopeReader,
)
from src.modules.network.managed_runtime.infra.successor_reads import (
    ManagedSuccessorReader,
)
from src.modules.network.managed_runtime.interfaces import (
    IManagedAdmissionCommand,
    IManagedAdmissionService,
    IManagedBarrierService,
    IManagedEpochService,
    IManagedFinalityCommand,
    IManagedInitialWindowCommand,
    IManagedInstallationCommand,
    IManagedInstallationService,
    IManagedRevocationCommand,
    IManagedRevocationService,
    IManagedRuntimeAuthority,
    IManagedSuccessorWindowCommand,
    IManagedWindowService,
)


class ManagedRuntimeProvider(Provider):
    scope = Scope.REQUEST
    successor_reader = provide(ManagedSuccessorReader)
    successor_command = provide(
        ManagedSuccessorWindowCommand, provides=IManagedSuccessorWindowCommand
    )
    revocation_command = provide(
        ManagedRevocationCommand, provides=IManagedRevocationCommand
    )
    revocation_repo = provide(ManagedRevocationRepository)
    revocation_service = provide(
        ManagedRevocationService, provides=IManagedRevocationService
    )
    admission_command = provide(
        ManagedAdmissionCommand, provides=IManagedAdmissionCommand
    )
    finality = provide(
        ManagedFinalityCommand, provides=IManagedFinalityCommand
    )
    installation_scope_reader = provide(ManagedInstallationScopeReader)
    installation_command = provide(
        ManagedInstallationCommand, provides=IManagedInstallationCommand
    )
    initial_window_command = provide(
        ManagedInitialWindowCommand, provides=IManagedInitialWindowCommand
    )
    authority = provide(
        ManagedRuntimeAuthority, provides=IManagedRuntimeAuthority
    )
    installation_repo = provide(ManagedInstallationRepository)
    installation_service = provide(
        ManagedInstallationService, provides=IManagedInstallationService
    )
    epoch_repo = provide(ManagedEpochRepository)
    epoch_service = provide(ManagedEpochService, provides=IManagedEpochService)
    window_repo = provide(ManagedWindowRepository)
    window_service = provide(
        ManagedWindowService, provides=IManagedWindowService
    )
    barrier_repo = provide(ManagedBarrierRepository)
    barrier_service = provide(
        ManagedBarrierService, provides=IManagedBarrierService
    )
    admission_repo = provide(ManagedAdmissionRepository)
    admission_service = provide(
        ManagedAdmissionService, provides=IManagedAdmissionService
    )
