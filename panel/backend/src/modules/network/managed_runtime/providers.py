from dishka import Provider, Scope, provide

from src.modules.network.managed_runtime.app.authority import (
    ManagedRuntimeAuthority,
)
from src.modules.network.managed_runtime.app.barriers import (
    ManagedFinalityCommand,
)
from src.modules.network.managed_runtime.app.installations import (
    ManagedInstallationCommand,
)
from src.modules.network.managed_runtime.app.services import (
    ManagedAdmissionService,
    ManagedBarrierService,
    ManagedEpochService,
    ManagedInstallationService,
    ManagedWindowService,
)
from src.modules.network.managed_runtime.app.windows import (
    ManagedInitialWindowCommand,
)
from src.modules.network.managed_runtime.infra.mysql import (
    ManagedAdmissionRepository,
    ManagedBarrierRepository,
    ManagedEpochRepository,
    ManagedInstallationRepository,
    ManagedWindowRepository,
)
from src.modules.network.managed_runtime.infra.scopes import (
    ManagedInstallationScopeReader,
)
from src.modules.network.managed_runtime.interfaces import (
    IManagedAdmissionService,
    IManagedBarrierService,
    IManagedEpochService,
    IManagedFinalityCommand,
    IManagedInitialWindowCommand,
    IManagedInstallationCommand,
    IManagedInstallationService,
    IManagedRuntimeAuthority,
    IManagedWindowService,
)


class ManagedRuntimeProvider(Provider):
    scope = Scope.REQUEST
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
