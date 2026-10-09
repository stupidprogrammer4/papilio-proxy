from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from sqlmodel import col

from src.modules.billing.wallet.domain.models import (
    TopupModel,
    WalletEntryModel,
    WalletModel,
)
from src.modules.billing.wallet.infra.tables import (
    TopupTable,
    WalletEntryTable,
    WalletTable,
)


class WalletRepository(MySQLPersistenceRepository[WalletModel]):
    table = WalletTable

    async def locked_for_customer(self, initial: WalletModel) -> WalletModel:
        await self.uow.execute(
            insert(WalletTable)
            .values(**initial.model_dump(exclude_unset=True))
            .prefix_with("IGNORE")
        )
        result = await self.uow.execute(
            select(WalletTable)
            .where(col(WalletTable.customer_id) == initial.customer_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one()

    async def by_customer(self, customer_id: int) -> WalletModel | None:
        result = await self.uow.execute(
            select(WalletTable).where(
                col(WalletTable.customer_id) == customer_id
            )
        )
        return result.scalar_one_or_none()

    async def entry_exists(self, reference: str) -> bool:
        result = await self.uow.execute(
            select(col(WalletEntryTable.id)).where(
                col(WalletEntryTable.reference) == reference
            )
        )
        return result.scalar_one_or_none() is not None

    async def record(
        self,
        wallet: WalletModel,
        entry: WalletEntryModel,
    ) -> WalletModel:
        await self.update_row_by_id(
            wallet.id, WalletModel.patch(balance_rial=entry.balance_after_rial)
        )
        self.uow.session.add(
            WalletEntryTable(**entry.model_dump(exclude_unset=True))
        )
        await self.uow.flush()
        await self.uow.refresh(wallet)
        return wallet


class TopupRepository(MySQLPersistenceRepository[TopupModel]):
    table = TopupTable

    async def owner_id(self, id: int) -> int | None:
        """Immutable FK identity chooses locks; it is not settlement proof."""
        result = await self.uow.execute(
            select(col(TopupTable.customer_id)).where(col(TopupTable.id) == id)
        )
        return result.scalar_one_or_none()

    async def by_request_key(self, key: str) -> TopupModel | None:
        result = await self.uow.execute(
            select(TopupTable)
            .where(col(TopupTable.request_key) == key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def locked(self, id: int) -> TopupModel | None:
        result = await self.uow.execute(
            select(TopupTable)
            .where(col(TopupTable.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def update_existing(
        self, topup: TopupModel, changes: TopupModel
    ) -> TopupModel:
        await self.update_row_by_id(topup.id, changes)
        await self.uow.refresh(topup)
        return topup

    async def page(
        self,
        status: str | None,
        customer_id: int | None,
        offset: int,
        limit: int,
    ) -> PagedType[TopupModel]:
        query = select(TopupTable)
        if status is not None:
            query = query.where(col(TopupTable.status) == status)
        if customer_id is not None:
            query = query.where(col(TopupTable.customer_id) == customer_id)
        query = query.order_by(col(TopupTable.id).desc())
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result
