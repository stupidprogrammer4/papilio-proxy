from dishka import Provider, Scope, provide

from src.modules.network.cores.app.inventory import CoreInventoryQuery
from src.modules.network.cores.app.queries import CoreExportQuery
from src.modules.network.cores.app.services import CoreService
from src.modules.network.cores.infra.inventory import CoreInventoryReader
from src.modules.network.cores.infra.mysql import CoreRepository
from src.modules.network.cores.infra.readers import CoreConfigurationReader
from src.modules.network.cores.interfaces import (
    ICoreExportQuery,
    ICoreInventoryQuery,
    ICoreService,
)


class CoreProvider(Provider):
    scope = Scope.REQUEST
    inventory_reader = provide(CoreInventoryReader)
    inventory_query = provide(CoreInventoryQuery, provides=ICoreInventoryQuery)
    repo = provide(CoreRepository)
    service = provide(CoreService, provides=ICoreService)
    reader = provide(CoreConfigurationReader)
    export = provide(CoreExportQuery, provides=ICoreExportQuery)
