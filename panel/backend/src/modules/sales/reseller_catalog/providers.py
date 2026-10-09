from dishka import Provider, Scope, provide

from src.modules.sales.reseller_catalog.app.commands import ResellerPlanCommand
from src.modules.sales.reseller_catalog.app.queries import (
    ResellerPlanHistoryQuery,
    ResellerPlanQuery,
)
from src.modules.sales.reseller_catalog.infra.mysql import (
    ResellerPlanChangeRepository,
    ResellerPlanRepository,
)
from src.modules.sales.reseller_catalog.infra.readers import ResellerPlanReader
from src.modules.sales.reseller_catalog.interfaces import (
    IResellerPlanCommand,
    IResellerPlanHistoryQuery,
    IResellerPlanQuery,
)


class ResellerCatalogProvider(Provider):
    scope = Scope.REQUEST
    agreements = provide(ResellerPlanRepository)
    changes = provide(ResellerPlanChangeRepository)
    reader = provide(ResellerPlanReader)
    command = provide(ResellerPlanCommand, provides=IResellerPlanCommand)
    query = provide(ResellerPlanQuery, provides=IResellerPlanQuery)
    history = provide(
        ResellerPlanHistoryQuery, provides=IResellerPlanHistoryQuery
    )
