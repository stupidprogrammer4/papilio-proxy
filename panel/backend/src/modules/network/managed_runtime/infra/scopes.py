from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import select
from sqlmodel import col

from src.modules.network.configurations.infra.tables import (
    ConfigurationTable,
    ProfileTable,
)
from src.modules.network.managed_runtime.domain.scopes import (
    ManagedInstallationScope,
    ManagedProfileScope,
    ManagedSubscriptionOwner,
)
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable


class ManagedInstallationScopeReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def initial(
        self, core_id: int, profile_limit: int
    ) -> ManagedInstallationScope:
        result = await self.uow.execute(
            select(
                col(ProfileTable.id),
                col(ProfileTable.configuration_id),
                col(ProfileTable.subscription_id),
                col(SubscriptionTable.customer_id),
            )
            .join(
                ConfigurationTable,
                col(ConfigurationTable.id)
                == col(ProfileTable.configuration_id),
            )
            .join(
                SubscriptionTable,
                col(SubscriptionTable.id) == col(ProfileTable.subscription_id),
            )
            .where(col(ConfigurationTable.core_id) == core_id)
            .order_by(col(ProfileTable.id))
            .limit(profile_limit)
        )
        rows = result.all()
        owners = {row.subscription_id: row.customer_id for row in rows}
        return ManagedInstallationScope(
            profiles=tuple(
                ManagedProfileScope(
                    row.id, row.configuration_id, row.subscription_id
                )
                for row in rows
            ),
            owners=tuple(
                ManagedSubscriptionOwner(id, owners[id])
                for id in sorted(owners)
            ),
        )

    async def lock_subscriptions(
        self, ids: list[int]
    ) -> tuple[ManagedSubscriptionOwner, ...]:
        result = await self.uow.execute(
            select(
                col(SubscriptionTable.id), col(SubscriptionTable.customer_id)
            )
            .where(col(SubscriptionTable.id).in_(ids))
            .order_by(col(SubscriptionTable.id))
            .with_for_update()
        )
        return tuple(
            ManagedSubscriptionOwner(row.id, row.customer_id)
            for row in result.all()
        )

    async def lock_configurations(self, core_id: int, limit: int) -> list[int]:
        result = await self.uow.execute(
            select(col(ConfigurationTable.id))
            .where(col(ConfigurationTable.core_id) == core_id)
            .order_by(col(ConfigurationTable.id))
            .limit(limit)
            .with_for_update()
        )
        return list(result.scalars())

    async def current_profiles(
        self, configuration_ids: list[int], limit: int
    ) -> tuple[ManagedProfileScope, ...]:
        result = await self.uow.execute(
            select(
                col(ProfileTable.id),
                col(ProfileTable.configuration_id),
                col(ProfileTable.subscription_id),
            )
            .where(col(ProfileTable.configuration_id).in_(configuration_ids))
            .order_by(col(ProfileTable.id))
            .limit(limit)
            .with_for_update(read=True)
        )
        return tuple(
            ManagedProfileScope(
                row.id, row.configuration_id, row.subscription_id
            )
            for row in result.all()
        )
