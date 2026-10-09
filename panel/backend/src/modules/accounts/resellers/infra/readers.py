from papilio.infra.db.tools.read import fetch_page
from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import select
from sqlmodel import col

from src.modules.accounts.customers.domain.models import CustomerModel
from src.modules.accounts.customers.infra.tables import CustomerTable
from src.modules.accounts.resellers.domain.results import (
    OwnedResellerCustomer,
    ResellerSessionFacts,
)
from src.modules.accounts.resellers.infra.tables import (
    ResellerAccountTable,
    ResellerCustomerTable,
    ResellerSessionTable,
    ResellerTable,
)


class ResellerSessionReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def by_token(self, token_hash: str) -> ResellerSessionFacts | None:
        result = await self.uow.execute(
            select(ResellerTable, ResellerAccountTable, ResellerSessionTable)
            .join(
                ResellerAccountTable,
                col(ResellerAccountTable.reseller_id) == col(ResellerTable.id),
            )
            .join(
                ResellerSessionTable,
                col(ResellerSessionTable.account_id)
                == col(ResellerAccountTable.id),
            )
            .where(col(ResellerSessionTable.token_hash) == token_hash)
        )
        row = result.one_or_none()
        return (
            None
            if row is None
            else ResellerSessionFacts(
                row.ResellerTable,
                row.ResellerAccountTable,
                row.ResellerSessionTable,
            )
        )


class ResellerCustomerReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def owned(
        self, reseller_id: int, customer_id: int
    ) -> OwnedResellerCustomer | None:
        result = await self.uow.execute(
            select(ResellerTable, CustomerTable)
            .join(
                ResellerCustomerTable,
                col(ResellerCustomerTable.reseller_id)
                == col(ResellerTable.id),
            )
            .join(
                CustomerTable,
                col(CustomerTable.id)
                == col(ResellerCustomerTable.customer_id),
            )
            .where(
                col(ResellerTable.id) == reseller_id,
                col(CustomerTable.id) == customer_id,
            )
        )
        row = result.one_or_none()
        return (
            None
            if row is None
            else OwnedResellerCustomer(row.ResellerTable, row.CustomerTable)
        )

    async def page(
        self, reseller_id: int, q: str | None, offset: int, limit: int
    ) -> PagedType[CustomerModel]:
        query = (
            select(CustomerTable)
            .join(
                ResellerCustomerTable,
                col(ResellerCustomerTable.customer_id)
                == col(CustomerTable.id),
            )
            .where(col(ResellerCustomerTable.reseller_id) == reseller_id)
        )
        if q:
            query = query.where(col(CustomerTable.display_name).like(f"%{q}%"))
        result = await fetch_page(
            self.uow,
            query.order_by(col(CustomerTable.id).desc()),
            offset=offset,
            limit=limit,
        )
        return result
