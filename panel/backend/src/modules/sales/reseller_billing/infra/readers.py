from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import select
from sqlmodel import col

from src.modules.accounts.resellers.domain.models import (
    ResellerAccountModel,
    ResellerModel,
)
from src.modules.accounts.resellers.infra.tables import (
    ResellerAccountTable,
    ResellerCustomerTable,
    ResellerTable,
)


class ResellerBillingReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def owner(
        self, customer_id: int, lock: bool = False
    ) -> ResellerModel | None:
        query = (
            select(ResellerTable)
            .join(
                ResellerCustomerTable,
                col(ResellerCustomerTable.reseller_id)
                == col(ResellerTable.id),
            )
            .where(col(ResellerCustomerTable.customer_id) == customer_id)
        )
        if lock:
            query = query.with_for_update().execution_options(
                populate_existing=True
            )
        result = await self.uow.execute(query)
        return result.scalar_one_or_none()

    async def account(
        self, reseller_id: int, id: int
    ) -> ResellerAccountModel | None:
        result = await self.uow.execute(
            select(ResellerAccountTable)
            .where(
                col(ResellerAccountTable.reseller_id) == reseller_id,
                col(ResellerAccountTable.id) == id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()
