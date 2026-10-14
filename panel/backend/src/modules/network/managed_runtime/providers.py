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
from src.modules.network.managed_runtime.app.epoch_seals import (
    ManagedEpochSealCommand,
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
    ManagedEpochSealService,
    ManagedEpochService,
    ManagedInstallationService,
    ManagedOperationBatchService,
    ManagedRevocationService,
    ManagedWindowService,
)
from src.modules.network.managed_runtime.app.successors import (
    ManagedSuccessorWindowCommand,
)
from src.modules.network.managed_runtime.app.window_batches import (
    ManagedInitialWindowBatchCommand,
)
from src.modules.network.managed_runtime.app.window_final_batches import (
    ManagedFinalityBatchCommand,
)
from src.modules.network.managed_runtime.app.windows import (
    ManagedInitialWindowCommand,
)
from src.modules.network.managed_runtime.infra.epoch_seal_mysql import (
    ManagedEpochSealRepository,
)
from src.modules.network.managed_runtime.infra.epoch_seal_reads import (
    ManagedEpochSealReader,
)
from src.modules.network.managed_runtime.infra.mysql import (
    ManagedAdmissionRepository,
    ManagedBarrierRepository,
    ManagedEpochRepository,
    ManagedInstallationRepository,
    ManagedOperationBatchRepository,
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
    IManagedEpochSealCommand,
    IManagedEpochSealService,
    IManagedEpochService,
    IManagedFinalityBatchCommand,
    IManagedFinalityCommand,
    IManagedInitialWindowBatchCommand,
    IManagedInitialWindowCommand,
    IManagedInstallationCommand,
    IManagedInstallationService,
    IManagedOperationBatchService,
    IManagedRevocationCommand,
    IManagedRevocationService,
    IManagedRuntimeAuthority,
    IManagedSuccessorWindowCommand,
    IManagedWindowService,
)


class ManagedRuntimeProvider(Provider):
    scope = Scope.REQUEST
    successor_reader = provide(ManagedSuccessorReader)
    epoch_seal_repository = provide(ManagedEpochSealRepository)
    epoch_seal_reader = provide(ManagedEpochSealReader)
    epoch_seal_service = provide(
        ManagedEpochSealService, provides=IManagedEpochSealService
    )
    epoch_seal_command = provide(
        ManagedEpochSealCommand, provides=IManagedEpochSealCommand
    )
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
    finality_batch = provide(
        ManagedFinalityBatchCommand, provides=IManagedFinalityBatchCommand
    )
    installation_scope_reader = provide(ManagedInstallationScopeReader)
    installation_command = provide(
        ManagedInstallationCommand, provides=IManagedInstallationCommand
    )
    initial_window_command = provide(
        ManagedInitialWindowCommand, provides=IManagedInitialWindowCommand
    )
    initial_window_batch_command = provide(
        ManagedInitialWindowBatchCommand,
        provides=IManagedInitialWindowBatchCommand,
    )
    authority = provide(
        ManagedRuntimeAuthority, provides=IManagedRuntimeAuthority
    )
    installation_repo = provide(ManagedInstallationRepository)
    operation_batch_repo = provide(ManagedOperationBatchRepository)
    operation_batch_service = provide(
        ManagedOperationBatchService, provides=IManagedOperationBatchService
    )
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
