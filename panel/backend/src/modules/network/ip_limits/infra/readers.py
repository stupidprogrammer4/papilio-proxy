from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import select
from sqlmodel import col

from src.modules.network.configurations.infra.tables import (
    ConfigurationTable,
    ProfileTable,
)
from src.modules.network.ip_limits.domain.results import IpAssignmentFacts


class NodeSubscriptionReader:
    """Current bounded profile/configuration assignment facts, not policy."""

    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def assignment_facts(
        self, node_id: int, subscription_id: int, limit: int
    ) -> list[IpAssignmentFacts]:
        result = await self.uow.execute(
            select(
                col(ProfileTable.id).label("profile_id"),
                col(ConfigurationTable.revision).label(
                    "configuration_revision"
                ),
                col(ProfileTable.applied_generation),
                col(ProfileTable.applied_revision),
            )
            .select_from(ConfigurationTable)
            .join(
                ProfileTable,
                col(ProfileTable.configuration_id)
                == col(ConfigurationTable.id),
            )
            .where(
                col(ConfigurationTable.node_id) == node_id,
                col(ProfileTable.subscription_id) == subscription_id,
            )
            .order_by(col(ConfigurationTable.id), col(ProfileTable.id))
            .limit(limit)
            .with_for_update(read=True)
        )
        return [IpAssignmentFacts(**row._mapping) for row in result]
