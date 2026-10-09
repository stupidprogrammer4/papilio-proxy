from dishka import Provider, Scope, provide

from src.modules.sales.catalog.app.bundles import PlanConfigurationQuery
from src.modules.sales.catalog.app.services import PlanService
from src.modules.sales.catalog.infra.bundles import PlanConfigurationReader
from src.modules.sales.catalog.infra.mysql import PlanRepository
from src.modules.sales.catalog.interfaces import (
    IPlanConfigurationQuery,
    IPlanService,
)


class CatalogProvider(Provider):
    bundles_reader = provide(PlanConfigurationReader)
    bundles_query = provide(
        PlanConfigurationQuery, provides=IPlanConfigurationQuery
    )
    scope = Scope.REQUEST
    plan_repository = provide(PlanRepository)
    plan_service = provide(PlanService, provides=IPlanService)
