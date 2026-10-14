from dishka import Provider, Scope, provide

from src.modules.network.provisioning.app.batches import (
    ProvisionRequestBatchService,
    ProvisionTaskBatchService,
)
from src.modules.network.provisioning.app.commands import ProvisioningCommand
from src.modules.network.provisioning.app.queries import ProvisioningQuery
from src.modules.network.provisioning.infra.mysql import (
    ProvisionRequestRepository,
    ProvisionTaskRepository,
)
from src.modules.network.provisioning.infra.readers import (
    ProvisioningFactsReader,
)
from src.modules.network.provisioning.interfaces import (
    IProvisioningCommand,
    IProvisioningQuery,
    IProvisionRequestBatchService,
    IProvisionTaskBatchService,
)
from src.modules.network.provisioning.tasks.schedulers.checks import (
    PrepareProvision,
    ScanProvisioning,
)


class ProvisioningProvider(Provider):
    scope = Scope.REQUEST
    requests = provide(ProvisionRequestRepository)
    tasks = provide(ProvisionTaskRepository)
    facts = provide(ProvisioningFactsReader)
    command = provide(ProvisioningCommand, provides=IProvisioningCommand)
    query = provide(ProvisioningQuery, provides=IProvisioningQuery)
    request_batch = provide(
        ProvisionRequestBatchService, provides=IProvisionRequestBatchService
    )
    task_batch = provide(
        ProvisionTaskBatchService, provides=IProvisionTaskBatchService
    )
    prepare_task = provide(PrepareProvision)
    scan_task = provide(ScanProvisioning)
