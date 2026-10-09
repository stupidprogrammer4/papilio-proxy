from datetime import datetime

from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import func, or_, select
from sqlmodel import col

from src.modules.accounts.customers.infra.tables import CustomerTable
from src.modules.billing.wallet.infra.tables import WalletTable
from src.modules.sales.attention.domain.renewal import CustomerRenewalFacts
from src.modules.sales.attention.domain.results import (
    SubscriptionAttentionFacts,
)
from src.modules.sales.attention.infra.tables import SubscriptionAttentionTable
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable


class SubscriptionAttentionReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def due_ids(self, before: datetime, limit: int) -> list[int]:
        result = await self.uow.execute(
            select(col(SubscriptionTable.id))
            .outerjoin(
                SubscriptionAttentionTable,
                col(SubscriptionAttentionTable.subscription_id)
                == col(SubscriptionTable.id),
            )
            .where(
                or_(
                    col(SubscriptionAttentionTable.checked_at).is_(None),
                    col(SubscriptionAttentionTable.checked_at) <= before,
                )
            )
            .order_by(
                col(SubscriptionAttentionTable.checked_at),
                col(SubscriptionTable.id),
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def page(
        self,
        status: str | None,
        customer_id: int | None,
        q: str | None,
        offset: int,
        limit: int,
    ) -> PagedType[SubscriptionAttentionFacts]:
        query = (
            select(
                SubscriptionAttentionTable, SubscriptionTable, CustomerTable
            )
            .join(
                SubscriptionTable,
                col(SubscriptionTable.id)
                == col(SubscriptionAttentionTable.subscription_id),
            )
            .join(
                CustomerTable,
                col(CustomerTable.id) == col(SubscriptionTable.customer_id),
            )
        )
        if status is not None:
            query = query.where(
                col(SubscriptionAttentionTable.status) == status
            )
        if customer_id is not None:
            query = query.where(
                col(SubscriptionTable.customer_id) == customer_id
            )
        if q:
            query = query.where(
                col(CustomerTable.display_name).contains(q, autoescape=True)
            )
        count = await self.uow.execute(
            select(func.count()).select_from(query.subquery())
        )
        result = await self.uow.execute(
            query.order_by(
                col(SubscriptionAttentionTable.checked_at).desc(),
                col(SubscriptionAttentionTable.id).desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return PagedType(
            items=[
                SubscriptionAttentionFacts(
                    row.SubscriptionAttentionTable,
                    row.SubscriptionTable,
                    row.CustomerTable,
                )
                for row in result
            ],
            total_items=count.scalar_one(),
        )


class CustomerRenewalReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def owned_current(
        self, subscription_id: int, customer_id: int
    ) -> CustomerRenewalFacts | None:
        result = await self.uow.execute(
            select(SubscriptionTable)
            .where(
                col(SubscriptionTable.id) == subscription_id,
                col(SubscriptionTable.customer_id) == customer_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        subscription = result.scalar_one_or_none()
        if subscription is None:
            return None
        payer_id = subscription.payer_customer_id or customer_id
        result = await self.uow.execute(
            select(CustomerTable)
            .where(col(CustomerTable.id).in_([customer_id, payer_id]))
            .order_by(col(CustomerTable.id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        customers = {row.id: row for row in result.scalars().all()}
        return CustomerRenewalFacts(
            subscription, customers.get(customer_id), customers.get(payer_id)
        )

    async def own_wallet_balance_current(self, customer_id: int) -> int:
        result = await self.uow.execute(
            select(col(WalletTable.balance_rial))
            .where(col(WalletTable.customer_id) == customer_id)
            .with_for_update()
        )
        balance = result.scalar_one_or_none()
        return 0 if balance is None else balance
