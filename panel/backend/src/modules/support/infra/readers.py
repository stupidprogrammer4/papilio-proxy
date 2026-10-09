from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import select
from sqlmodel import col

from src.modules.billing.wallet.infra.tables import TopupTable
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable


class SupportContextReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def subscription_owner(self, id: int) -> int | None:
        result = await self.uow.execute(
            select(col(SubscriptionTable.customer_id)).where(
                col(SubscriptionTable.id) == id
            )
        )
        return result.scalar_one_or_none()

    async def topup_owner(self, id: int) -> int | None:
        result = await self.uow.execute(
            select(col(TopupTable.customer_id)).where(col(TopupTable.id) == id)
        )
        return result.scalar_one_or_none()
