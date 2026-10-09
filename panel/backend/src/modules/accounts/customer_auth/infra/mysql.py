from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import delete, select
from sqlmodel import col

from src.modules.accounts.customer_auth.domain.models import (
    CustomerLoginModel,
    CustomerSessionModel,
)
from src.modules.accounts.customer_auth.infra.tables import (
    CustomerLoginTable,
    CustomerSessionTable,
)


class CustomerLoginRepository:
    table = CustomerLoginTable

    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def create(self, data: CustomerLoginModel) -> None:
        self.uow.session.add(CustomerLoginTable(**data.model_dump()))
        await self.uow.flush()

    async def get(self, token_hash: str) -> CustomerLoginModel | None:
        result = await self.uow.execute(
            select(CustomerLoginTable).where(
                col(CustomerLoginTable.token_hash) == token_hash
            )
        )
        return result.scalar_one_or_none()

    async def locked(self, token_hash: str) -> CustomerLoginModel | None:
        result = await self.uow.execute(
            select(CustomerLoginTable)
            .where(col(CustomerLoginTable.token_hash) == token_hash)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def remove_customer(self, customer_id: int) -> None:
        await self.uow.execute(
            delete(self.table).where(
                col(self.table.customer_id) == customer_id
            )
        )

    async def remove(self, token_hash: str) -> None:
        await self.uow.execute(
            delete(CustomerLoginTable).where(
                col(CustomerLoginTable.token_hash) == token_hash
            )
        )


class CustomerSessionRepository:
    table = CustomerSessionTable

    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def create(self, data: CustomerSessionModel) -> None:
        self.uow.session.add(CustomerSessionTable(**data.model_dump()))
        await self.uow.flush()

    async def remove_customer(self, customer_id: int) -> None:
        await self.uow.execute(
            delete(self.table).where(
                col(self.table.customer_id) == customer_id
            )
        )

    async def remove(self, token_hash: str) -> None:
        await self.uow.execute(
            delete(CustomerSessionTable).where(
                col(CustomerSessionTable.token_hash) == token_hash
            )
        )
