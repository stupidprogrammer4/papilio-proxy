from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import func, select
from sqlmodel import col

from src.modules.accounts.customers.domain.configurations import (
    CustomerConfigurationFacts,
)
from src.modules.network.configurations.infra.tables import (
    ConfigurationTable,
    ProfileTable,
)
from src.modules.network.nodes.infra.tables import NodeTable
from src.modules.sales.catalog.infra.tables import PlanTable
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable


class CustomerConfigurationReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def page(
        self,
        customer_id: int,
        subscription_id: int | None,
        offset: int,
        limit: int,
    ) -> PagedType[CustomerConfigurationFacts]:
        query = (
            select(
                ProfileTable,
                SubscriptionTable,
                PlanTable,
                ConfigurationTable,
                NodeTable,
            )
            .join(
                SubscriptionTable,
                col(SubscriptionTable.id) == col(ProfileTable.subscription_id),
            )
            .join(
                PlanTable, col(PlanTable.id) == col(SubscriptionTable.plan_id)
            )
            .join(
                ConfigurationTable,
                col(ConfigurationTable.id)
                == col(ProfileTable.configuration_id),
            )
            .join(
                NodeTable, col(NodeTable.id) == col(ConfigurationTable.node_id)
            )
            .where(col(SubscriptionTable.customer_id) == customer_id)
            .order_by(col(ProfileTable.id).desc())
        )
        if subscription_id is not None:
            query = query.where(col(SubscriptionTable.id) == subscription_id)
        count = await self.uow.execute(
            select(func.count()).select_from(query.order_by(None).subquery())
        )
        rows = await self.uow.execute(query.offset(offset).limit(limit))
        return PagedType(
            items=[
                CustomerConfigurationFacts(
                    row.ProfileTable,
                    row.SubscriptionTable,
                    row.PlanTable,
                    row.ConfigurationTable,
                    row.NodeTable,
                )
                for row in rows
            ],
            total_items=count.scalar_one(),
        )
