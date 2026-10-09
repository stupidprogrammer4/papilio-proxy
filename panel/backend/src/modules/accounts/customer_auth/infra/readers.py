from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import select
from sqlmodel import col

from src.modules.accounts.customer_auth.domain.results import (
    CustomerSessionFacts,
)
from src.modules.accounts.customer_auth.infra.tables import (
    CustomerSessionTable,
)
from src.modules.accounts.customers.infra.tables import CustomerTable


class CustomerSessionReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def by_token(self, token_hash: str) -> CustomerSessionFacts | None:
        result = await self.uow.execute(
            select(CustomerTable, CustomerSessionTable)
            .join(
                CustomerSessionTable,
                col(CustomerSessionTable.customer_id) == col(CustomerTable.id),
            )
            .where(col(CustomerSessionTable.token_hash) == token_hash)
        )
        row = result.one_or_none()
        return (
            None
            if row is None
            else CustomerSessionFacts(
                row.CustomerTable, row.CustomerSessionTable
            )
        )
