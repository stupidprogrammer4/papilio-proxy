from dishka import Provider, Scope, provide

from src.modules.network.core_runtime.app.budget import (
    CoreProvisioningBudgetQuery,
)
from src.modules.network.core_runtime.app.commands import CoreRuntimeCommand
from src.modules.network.core_runtime.app.installed import (
    InstalledProfileQuery,
)
from src.modules.network.core_runtime.app.installed_usage import (
    InstalledUsageQuery,
)
from src.modules.network.core_runtime.app.provisioning import (
    CoreProvisioningCommand,
    CoreProvisioningQuery,
)
from src.modules.network.core_runtime.app.queries import CoreRuntimeQuery
from src.modules.network.core_runtime.app.services import (
    RuntimeCommandService,
    RuntimeRevisionService,
    RuntimeStateService,
)
from src.modules.network.core_runtime.app.usage_observations import (
    CoreUsageObservationCommand,
)
from src.modules.network.core_runtime.app.usage_policy import (
    CoreUsagePolicyQuery,
)
from src.modules.network.core_runtime.infra.budget import (
    RuntimeProvisioningBudgetReader,
)
from src.modules.network.core_runtime.infra.metadata import (
    RuntimeRevisionMetadataReader,
)
from src.modules.network.core_runtime.infra.mysql import (
    RuntimeCommandRepository,
    RuntimeRevisionRepository,
    RuntimeStateRepository,
)
from src.modules.network.core_runtime.infra.provisioning import (
    CoreProvisioningReader,
)
from src.modules.network.core_runtime.infra.readers import (
    RuntimeSnapshotReader,
)
from src.modules.network.core_runtime.infra.usage import (
    RuntimeUsageEndpointReader,
)
from src.modules.network.core_runtime.interfaces import (
    ICoreProvisioningBudgetQuery,
    ICoreProvisioningCommand,
    ICoreProvisioningQuery,
    ICoreRuntimeCommand,
    ICoreRuntimeQuery,
    ICoreUsageObservationCommand,
    ICoreUsagePolicyQuery,
    IInstalledProfileQuery,
    IInstalledUsageQuery,
    IRuntimeCommandService,
    IRuntimeRevisionService,
    IRuntimeStateService,
)
from src.modules.network.core_runtime.tasks.schedulers.provisioning import (
    EnsureCoreProvisioning,
    ScanCoreProvisioning,
)
from src.modules.network.core_runtime.tasks.schedulers.recovery import (
    RecoverCoreRuntime,
    ScanCoreRuntime,
)


class CoreRuntimeProvider(Provider):
    scope = Scope.REQUEST
    usage_observations = provide(
        CoreUsageObservationCommand, provides=ICoreUsageObservationCommand
    )
    usage_endpoint_reader = provide(RuntimeUsageEndpointReader)
    usage_policy = provide(
        CoreUsagePolicyQuery, provides=ICoreUsagePolicyQuery
    )
    installed_usage = provide(
        InstalledUsageQuery, provides=IInstalledUsageQuery
    )
    budget_reader = provide(RuntimeProvisioningBudgetReader)
    budget = provide(
        CoreProvisioningBudgetQuery, provides=ICoreProvisioningBudgetQuery
    )
    provisioning_reader = provide(CoreProvisioningReader)
    provisioning_query = provide(
        CoreProvisioningQuery, provides=ICoreProvisioningQuery
    )
    provisioning_command = provide(
        CoreProvisioningCommand, provides=ICoreProvisioningCommand
    )
    ensure_provision_task = provide(EnsureCoreProvisioning)
    scan_provision_task = provide(ScanCoreProvisioning)
    state_repo = provide(RuntimeStateRepository)
    revision_repo = provide(RuntimeRevisionRepository)
    command_repo = provide(RuntimeCommandRepository)
    states = provide(RuntimeStateService, provides=IRuntimeStateService)
    revisions = provide(
        RuntimeRevisionService, provides=IRuntimeRevisionService
    )
    commands = provide(RuntimeCommandService, provides=IRuntimeCommandService)
    reader = provide(RuntimeSnapshotReader)
    installed = provide(InstalledProfileQuery, provides=IInstalledProfileQuery)
    metadata = provide(RuntimeRevisionMetadataReader)
    query = provide(CoreRuntimeQuery, provides=ICoreRuntimeQuery)
    command = provide(CoreRuntimeCommand, provides=ICoreRuntimeCommand)
    recover_task = provide(RecoverCoreRuntime)
    scan_task = provide(ScanCoreRuntime)
