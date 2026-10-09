from src.config.pagination import ServicePage, page_size
from src.config.settings import PapilioSettings
from src.modules.sales.catalog.domain.bundles import (
    PlanConfigurationRead,
    PlanConfigurationSearch,
)
from src.modules.sales.catalog.infra.bundles import PlanConfigurationReader
from src.modules.sales.catalog.interfaces import IPlanService


class PlanConfigurationQuery:
    def __init__(
        self,
        reader: PlanConfigurationReader,
        plans: IPlanService,
        settings: PapilioSettings,
    ) -> None:
        self.reader = reader
        self.plans = plans
        self.settings = settings

    async def search(
        self, plan_id: int, data: PlanConfigurationSearch, public: bool = False
    ) -> ServicePage[PlanConfigurationRead]:
        plan = (
            await self.plans.get_active(plan_id)
            if public
            else await self.plans.get(plan_id)
        )
        limit = page_size(self.settings, data.per_page)
        if plan.group_id is None:
            return ServicePage(items=[], total_items=0, per_page=limit)
        result = await self.reader.page(
            plan.group_id,
            True if public else None,
            (data.page - 1) * limit,
            limit,
        )
        items = [
            PlanConfigurationRead(
                configuration_id=row.configuration.id,
                node_id=row.node.id,
                node_label=row.node.label,
                label=row.membership.label or row.host.label,
                protocol=row.configuration.protocol,
                host_id=row.host.id,
                group_id=row.group.id,
                is_enabled=row.group.is_enabled
                and row.node.is_enabled
                and row.host.is_enabled
                and row.membership.is_enabled,
            )
            for row in result.items
        ]
        return ServicePage(
            items=items, total_items=result.total_items, per_page=limit
        )
