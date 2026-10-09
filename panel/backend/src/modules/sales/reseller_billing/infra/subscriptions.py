from papilio.infra.db.tools.read import fetch_page
from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import select
from sqlmodel import col

from src.modules.accounts.resellers.infra.tables import ResellerCustomerTable
from src.modules.sales.subscriptions.domain.models import SubscriptionModel
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable


class ResellerSubscriptionReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def owned(
        self, reseller_id: int, id: int
    ) -> SubscriptionModel | None:
        result = await self.uow.execute(
            select(SubscriptionTable)
            .join(
                ResellerCustomerTable,
                col(ResellerCustomerTable.customer_id)
                == col(SubscriptionTable.customer_id),
            )
            .where(
                col(ResellerCustomerTable.reseller_id) == reseller_id,
                col(SubscriptionTable.id) == id,
            )
        )
        return result.scalar_one_or_none()

    async def page(
        self,
        reseller_id: int,
        customer_id: int | None,
        status: str | None,
        offset: int,
        limit: int,
    ) -> PagedType[SubscriptionModel]:
        query = (
            select(SubscriptionTable)
            .join(
                ResellerCustomerTable,
                col(ResellerCustomerTable.customer_id)
                == col(SubscriptionTable.customer_id),
            )
            .where(col(ResellerCustomerTable.reseller_id) == reseller_id)
        )
        if customer_id is not None:
            query = query.where(
                col(SubscriptionTable.customer_id) == customer_id
            )
        if status is not None:
            query = query.where(col(SubscriptionTable.status) == status)
        result = await fetch_page(
            self.uow,
            query.order_by(col(SubscriptionTable.id).desc()),
            offset=offset,
            limit=limit,
        )
        return result
