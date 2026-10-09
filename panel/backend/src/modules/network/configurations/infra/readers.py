from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import and_, or_, select
from sqlmodel import col

from src.modules.accounts.customers.infra.tables import CustomerTable
from src.modules.network.configurations.domain.results import (
    ConfigurationServerFacts,
    ProfileFacts,
    SubscriptionConfigurationFacts,
)
from src.modules.network.configurations.infra.tables import (
    ConfigurationTable,
    ProfileTable,
)
from src.modules.network.cores.infra.tables import CoreTable
from src.modules.network.nodes.infra.tables import NodeTable
from src.modules.network.provisioning.infra.tables import ProvisionRequestTable
from src.modules.network.routing.infra.tables import (
    HostGroupTable,
    HostMembershipTable,
    HostTable,
)
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable


class ConfigurationFactsReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def profiles(
        self, configuration_id: int, limit: int
    ) -> list[ProfileFacts]:
        result = await self.uow.execute(
            select(
                ProfileTable,
                SubscriptionTable,
                CustomerTable,
                ProvisionRequestTable,
            )
            .join(
                SubscriptionTable,
                col(SubscriptionTable.id) == col(ProfileTable.subscription_id),
            )
            .join(
                CustomerTable,
                col(CustomerTable.id) == col(SubscriptionTable.customer_id),
            )
            .outerjoin(
                ProvisionRequestTable,
                and_(
                    col(ProvisionRequestTable.subscription_id)
                    == col(SubscriptionTable.id),
                    col(ProvisionRequestTable.generation)
                    == col(SubscriptionTable.renewal_count),
                ),
            )
            .where(col(ProfileTable.configuration_id) == configuration_id)
            .limit(limit)
        )
        return [
            ProfileFacts(
                customer=row.CustomerTable,
                profile=row.ProfileTable,
                subscription=row.SubscriptionTable,
                request_state=row.ProvisionRequestTable.state
                if row.ProvisionRequestTable
                else None,
            )
            for row in result
        ]

    async def server_configurations(
        self, configuration_ids: list[int]
    ) -> list[ConfigurationServerFacts]:
        result = await self.uow.execute(
            select(ConfigurationTable, NodeTable, CoreTable)
            .join(
                NodeTable, col(NodeTable.id) == col(ConfigurationTable.node_id)
            )
            .join(
                CoreTable, col(CoreTable.id) == col(ConfigurationTable.core_id)
            )
            .where(col(ConfigurationTable.id).in_(configuration_ids))
            .order_by(col(ConfigurationTable.id))
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        return [
            ConfigurationServerFacts(
                row.ConfigurationTable, row.NodeTable, row.CoreTable
            )
            for row in result
        ]

    async def profiles_many(
        self, configuration_ids: list[int], limit: int
    ) -> list[ProfileFacts]:
        result = await self.uow.execute(
            select(
                ProfileTable,
                SubscriptionTable,
                CustomerTable,
                ProvisionRequestTable,
            )
            .join(
                SubscriptionTable,
                col(SubscriptionTable.id) == col(ProfileTable.subscription_id),
            )
            .join(
                CustomerTable,
                col(CustomerTable.id) == col(SubscriptionTable.customer_id),
            )
            .outerjoin(
                ProvisionRequestTable,
                and_(
                    col(ProvisionRequestTable.subscription_id)
                    == col(SubscriptionTable.id),
                    col(ProvisionRequestTable.generation)
                    == col(SubscriptionTable.renewal_count),
                ),
            )
            .where(col(ProfileTable.configuration_id).in_(configuration_ids))
            .order_by(col(ProfileTable.id))
            .limit(limit)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        return [
            ProfileFacts(
                customer=row.CustomerTable,
                profile=row.ProfileTable,
                subscription=row.SubscriptionTable,
                request_state=row.ProvisionRequestTable.state
                if row.ProvisionRequestTable
                else None,
            )
            for row in result
        ]

    def _subscription_statement(self, subscription_id: int):
        return (
            select(
                CustomerTable,
                ProfileTable,
                SubscriptionTable,
                ConfigurationTable,
                NodeTable,
                HostTable,
                HostGroupTable,
                HostMembershipTable,
            )
            .join(
                SubscriptionTable,
                col(SubscriptionTable.id) == col(ProfileTable.subscription_id),
            )
            .join(
                CustomerTable,
                col(CustomerTable.id) == col(SubscriptionTable.customer_id),
            )
            .join(
                ConfigurationTable,
                col(ConfigurationTable.id)
                == col(ProfileTable.configuration_id),
            )
            .join(
                NodeTable, col(NodeTable.id) == col(ConfigurationTable.node_id)
            )
            .outerjoin(
                HostTable,
                and_(
                    col(HostTable.configuration_id)
                    == col(ConfigurationTable.id),
                    col(SubscriptionTable.group_id).is_not(None),
                ),
            )
            .outerjoin(
                HostMembershipTable,
                and_(
                    col(HostMembershipTable.host_id) == col(HostTable.id),
                    col(HostMembershipTable.group_id)
                    == col(SubscriptionTable.group_id),
                ),
            )
            .outerjoin(
                HostGroupTable,
                col(HostGroupTable.id) == col(SubscriptionTable.group_id),
            )
            .where(
                col(ProfileTable.subscription_id) == subscription_id,
                or_(
                    col(SubscriptionTable.group_id).is_(None),
                    col(HostMembershipTable.id).is_not(None),
                ),
            )
            .order_by(
                col(HostMembershipTable.sort_order),
                col(HostMembershipTable.id),
                col(ProfileTable.id),
            )
        )

    async def subscription(
        self, subscription_id: int, limit: int
    ) -> list[SubscriptionConfigurationFacts]:
        result = await self.uow.execute(
            self._subscription_statement(subscription_id).limit(limit)
        )
        return [
            SubscriptionConfigurationFacts(
                customer=row.CustomerTable,
                profile=row.ProfileTable,
                subscription=row.SubscriptionTable,
                configuration=row.ConfigurationTable,
                node=row.NodeTable,
                host=row.HostTable,
                group=row.HostGroupTable,
                membership=row.HostMembershipTable,
            )
            for row in result
        ]

    async def single_profile(
        self, subscription_id: int, profile_id: int, host_id: int | None
    ) -> SubscriptionConfigurationFacts | None:
        statement = self._subscription_statement(subscription_id).where(
            col(ProfileTable.id) == profile_id
        )
        statement = (
            statement.where(col(HostTable.id) == host_id)
            if host_id is not None
            else statement.where(col(HostTable.id).is_(None))
        )
        result = await self.uow.execute(statement)
        row = result.one_or_none()
        return (
            None
            if row is None
            else SubscriptionConfigurationFacts(
                row.CustomerTable,
                row.ProfileTable,
                row.SubscriptionTable,
                row.ConfigurationTable,
                row.NodeTable,
                row.HostTable,
                row.HostGroupTable,
                row.HostMembershipTable,
            )
        )
