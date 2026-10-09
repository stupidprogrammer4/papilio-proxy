from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import func, or_, select
from sqlmodel import col

from src.modules.accounts.customers.infra.tables import CustomerTable
from src.modules.sales.subscriptions.domain.results import (
    CustomerHoldCandidate,
)
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable


class CustomerHoldReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def candidates(
        self,
        statuses: list[str],
        services_enabled: bool,
        hold_pending: bool,
        limit: int,
    ) -> list[CustomerHoldCandidate]:
        result = await self.uow.execute(
            select(
                col(SubscriptionTable.id).label("subscription_id"),
                col(SubscriptionTable.customer_id),
            )
            .join(
                CustomerTable,
                col(CustomerTable.id) == col(SubscriptionTable.customer_id),
            )
            .where(
                or_(
                    col(CustomerTable.services_enabled).is_(services_enabled),
                    col(CustomerTable.service_hold_pending).is_(hold_pending),
                ),
                col(SubscriptionTable.status).in_(statuses),
            )
            .order_by(
                col(SubscriptionTable.lifecycle_checked_at),
                col(SubscriptionTable.id),
            )
            .limit(limit)
        )
        return [
            CustomerHoldCandidate(row.subscription_id, row.customer_id)
            for row in result
        ]

    async def outstanding_count(
        self, customer_id: int, statuses: list[str]
    ) -> int:
        result = await self.uow.execute(
            select(func.count(col(SubscriptionTable.id))).where(
                col(SubscriptionTable.customer_id) == customer_id,
                col(SubscriptionTable.status).in_(statuses),
            )
        )
        return result.scalar_one()
