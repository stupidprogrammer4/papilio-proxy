from papilio.infra.db.tools.read import fetch_page
from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import select
from sqlmodel import col

from src.modules.billing.wallet.domain.results import WalletLedgerFacts
from src.modules.billing.wallet.infra.tables import (
    WalletEntryTable,
    WalletTable,
)


class WalletLedgerReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def page(
        self, customer_id: int, reason: str | None, offset: int, limit: int
    ) -> PagedType[WalletLedgerFacts]:
        query = (
            select(WalletEntryTable)
            .join(
                WalletTable,
                col(WalletTable.id) == col(WalletEntryTable.wallet_id),
            )
            .where(col(WalletTable.customer_id) == customer_id)
        )
        if reason is not None:
            query = query.where(col(WalletEntryTable.reason) == reason)
        result = await fetch_page(
            self.uow,
            query.order_by(col(WalletEntryTable.id).desc()),
            offset=offset,
            limit=limit,
        )
        return PagedType(
            items=[
                WalletLedgerFacts(customer_id=customer_id, entry=entry)
                for entry in result.items
            ],
            total_items=result.total_items,
        )
