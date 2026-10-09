from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from sqlalchemy import select
from sqlmodel import col

from src.modules.network.ip_limits.domain.models import PurchasedIpPolicyModel
from src.modules.network.ip_limits.infra.tables import PurchasedIpPolicyTable


class PurchasedIpPolicyRepository(
    MySQLPersistenceRepository[PurchasedIpPolicyModel]
):
    table = PurchasedIpPolicyTable

    async def find(
        self, subscription_id: int
    ) -> PurchasedIpPolicyModel | None:
        result = await self.uow.execute(
            select(PurchasedIpPolicyTable).where(
                col(PurchasedIpPolicyTable.subscription_id) == subscription_id
            )
        )
        return result.scalar_one_or_none()

    async def current(
        self, subscription_id: int
    ) -> PurchasedIpPolicyModel | None:
        """Current immutable snapshot under owning Subscription write lock."""
        result = await self.uow.execute(
            select(PurchasedIpPolicyTable)
            .where(
                col(PurchasedIpPolicyTable.subscription_id) == subscription_id
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()
