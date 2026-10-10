from datetime import datetime

from papilio.infra.db.tools.read import fetch_page
from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import or_, select
from sqlmodel import col

from src.modules.network.configurations.infra.tables import (
    ConfigurationTable,
    ProfileTable,
)
from src.modules.network.managed_runtime.infra.tables import ManagedWindowTable
from src.modules.network.nodes.infra.tables import NodeTable
from src.modules.network.provisioning.domain.models import ProvisionTaskModel
from src.modules.network.provisioning.domain.results import (
    NodeProvisionFacts,
    ProvisionTarget,
)
from src.modules.network.provisioning.infra.tables import (
    ProvisionRequestTable,
    ProvisionTaskTable,
)
from src.modules.network.routing.infra.tables import (
    HostGroupTable,
    HostMembershipTable,
    HostTable,
)
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable


class ProvisioningFactsReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def managed_task_window_exists(
        self, task_id: int, current: bool = False
    ) -> bool:
        query = select(col(ManagedWindowTable.id)).where(
            col(ManagedWindowTable.provision_task_id) == task_id
        )
        if current:
            query = query.with_for_update(read=True)
        result = await self.uow.execute(select(query.exists()))
        return bool(result.scalar_one())

    async def targets(
        self,
        subscription_id: int,
        group_id: int | None,
        limit: int,
        current: bool = False,
    ) -> list[ProvisionTarget]:
        query = select(ConfigurationTable, NodeTable).join(
            NodeTable, col(NodeTable.id) == col(ConfigurationTable.node_id)
        )
        if group_id is None:
            query = query.join(
                ProfileTable,
                col(ProfileTable.configuration_id)
                == col(ConfigurationTable.id),
            ).where(col(ProfileTable.subscription_id) == subscription_id)
        else:
            query = (
                query.join(
                    HostTable,
                    col(HostTable.configuration_id)
                    == col(ConfigurationTable.id),
                )
                .join(
                    HostMembershipTable,
                    col(HostMembershipTable.host_id) == col(HostTable.id),
                )
                .join(
                    HostGroupTable,
                    col(HostGroupTable.id)
                    == col(HostMembershipTable.group_id),
                )
                .where(
                    col(HostGroupTable.id) == group_id,
                    col(HostGroupTable.is_enabled).is_(True),
                    col(HostTable.is_enabled).is_(True),
                    col(HostMembershipTable.is_enabled).is_(True),
                )
            )
        query = (
            query.where(col(NodeTable.is_enabled).is_(True))
            .distinct()
            .order_by(col(ConfigurationTable.id))
            .limit(limit)
        )
        if current:
            query = query.with_for_update(read=True).execution_options(
                populate_existing=True
            )
        result = await self.uow.execute(query)
        return [
            ProvisionTarget(row.ConfigurationTable, row.NodeTable)
            for row in result
        ]

    async def request_core_ids(self, request_id: int, limit: int) -> list[int]:
        result = await self.uow.execute(
            select(col(ConfigurationTable.core_id))
            .join(
                ProvisionTaskTable,
                col(ProvisionTaskTable.configuration_id)
                == col(ConfigurationTable.id),
            )
            .where(col(ProvisionTaskTable.request_id) == request_id)
            .distinct()
            .order_by(col(ConfigurationTable.core_id))
            .limit(limit)
        )
        return list(result.scalars())

    async def node_tasks(
        self,
        node_id: int,
        core_id: int | None,
        states: list[str],
        request_states: list[str],
        before: datetime | None,
        offset: int,
        limit: int,
    ) -> PagedType[ProvisionTaskModel]:
        query = (
            select(ProvisionTaskTable)
            .join(
                ConfigurationTable,
                col(ConfigurationTable.id)
                == col(ProvisionTaskTable.configuration_id),
            )
            .join(
                ProvisionRequestTable,
                col(ProvisionRequestTable.id)
                == col(ProvisionTaskTable.request_id),
            )
            .join(
                SubscriptionTable,
                col(SubscriptionTable.id)
                == col(ProvisionRequestTable.subscription_id),
            )
            .where(
                col(ProvisionTaskTable.node_id) == node_id,
                col(ProvisionTaskTable.state).in_(states),
            )
            .order_by(col(ProvisionTaskTable.id))
        )
        if core_id is not None:
            query = query.where(col(ConfigurationTable.core_id) == core_id)
        if before is not None:
            query = query.where(
                col(ProvisionTaskTable.available_at) <= before,
                col(ProvisionRequestTable.state).in_(request_states),
                col(ProvisionRequestTable.generation)
                == col(SubscriptionTable.renewal_count),
                or_(
                    col(ProvisionTaskTable.state) != "leased",
                    col(ProvisionTaskTable.claim_until).is_(None),
                    col(ProvisionTaskTable.claim_until) <= before,
                ),
            )
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result

    async def node_task(
        self, task_id: int, current: bool = False
    ) -> NodeProvisionFacts | None:
        query = (
            select(
                ProvisionTaskTable,
                ProvisionRequestTable,
                SubscriptionTable,
                ProfileTable,
                ConfigurationTable,
            )
            .join(
                ProvisionRequestTable,
                col(ProvisionRequestTable.id)
                == col(ProvisionTaskTable.request_id),
            )
            .join(
                SubscriptionTable,
                col(SubscriptionTable.id)
                == col(ProvisionRequestTable.subscription_id),
            )
            .join(
                ProfileTable,
                col(ProfileTable.id) == col(ProvisionTaskTable.profile_id),
            )
            .join(
                ConfigurationTable,
                col(ConfigurationTable.id)
                == col(ProvisionTaskTable.configuration_id),
            )
            .where(col(ProvisionTaskTable.id) == task_id)
        )
        if current:
            query = query.with_for_update(read=True).execution_options(
                populate_existing=True
            )
        result = await self.uow.execute(query)
        row = result.one_or_none()
        return (
            None
            if row is None
            else NodeProvisionFacts(
                row.ProvisionTaskTable,
                row.ProvisionRequestTable,
                row.SubscriptionTable,
                row.ProfileTable,
                row.ConfigurationTable,
            )
        )
