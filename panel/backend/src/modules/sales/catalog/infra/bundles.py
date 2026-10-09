from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import func, select
from sqlmodel import col

from src.modules.network.configurations.infra.tables import ConfigurationTable
from src.modules.network.nodes.infra.tables import NodeTable
from src.modules.network.routing.infra.tables import (
    HostGroupTable,
    HostMembershipTable,
    HostTable,
)
from src.modules.sales.catalog.domain.bundles import PlanConfigurationFacts


class PlanConfigurationReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def page(
        self, group_id: int, enabled: bool | None, offset: int, limit: int
    ) -> PagedType[PlanConfigurationFacts]:
        query = (
            select(
                ConfigurationTable,
                NodeTable,
                HostTable,
                HostGroupTable,
                HostMembershipTable,
            )
            .join(
                NodeTable,
                col(NodeTable.id) == col(ConfigurationTable.node_id),
            )
            .join(
                HostTable,
                col(HostTable.configuration_id) == col(ConfigurationTable.id),
            )
            .join(
                HostMembershipTable,
                col(HostMembershipTable.host_id) == col(HostTable.id),
            )
            .join(
                HostGroupTable,
                col(HostGroupTable.id) == col(HostMembershipTable.group_id),
            )
            .where(col(HostGroupTable.id) == group_id)
            .order_by(
                col(HostMembershipTable.sort_order),
                col(HostMembershipTable.id),
            )
        )
        if enabled is not None:
            query = query.where(
                col(NodeTable.is_enabled) == enabled,
                col(HostGroupTable.is_enabled) == enabled,
                col(HostMembershipTable.is_enabled) == enabled,
                col(HostTable.is_enabled) == enabled,
            )
        count = await self.uow.execute(
            select(func.count()).select_from(query.order_by(None).subquery())
        )
        rows = await self.uow.execute(query.offset(offset).limit(limit))
        return PagedType(
            items=[
                PlanConfigurationFacts(
                    row.ConfigurationTable,
                    row.NodeTable,
                    row.HostTable,
                    row.HostGroupTable,
                    row.HostMembershipTable,
                )
                for row in rows
            ],
            total_items=count.scalar_one(),
        )
