from datetime import datetime

from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import exists, func, or_, select
from sqlmodel import col

from src.modules.accounts.customers.infra.tables import CustomerTable
from src.modules.billing.reviews.domain.results import (
    PaymentMatchFacts,
    PaymentReviewFacts,
)
from src.modules.billing.reviews.infra.tables import PaymentReviewTable
from src.modules.billing.sms.infra.tables import SmsEventTable
from src.modules.billing.wallet.infra.tables import TopupTable


class PaymentReviewReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def due_ids(
        self,
        before: datetime,
        limit: int,
        pending_status: str,
        closed_status: str,
    ) -> list[int]:
        result = await self.uow.execute(
            select(col(TopupTable.id))
            .outerjoin(
                PaymentReviewTable,
                col(PaymentReviewTable.topup_id) == col(TopupTable.id),
            )
            .where(
                or_(
                    col(TopupTable.status) == pending_status,
                    col(PaymentReviewTable.status) != closed_status,
                )
            )
            .where(
                or_(
                    col(PaymentReviewTable.checked_at).is_(None),
                    col(PaymentReviewTable.checked_at) <= before,
                )
            )
            .order_by(col(PaymentReviewTable.checked_at), col(TopupTable.id))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def match_facts(
        self,
        topup_id: int,
        amount_rial: int,
        since: datetime,
        until: datetime,
        pending_status: str,
        settled_status: str,
    ) -> PaymentMatchFacts:
        used = exists(
            select(col(TopupTable.id)).where(
                col(TopupTable.status) == settled_status,
                col(TopupTable.bank_reference)
                == col(SmsEventTable.bank_reference),
            )
        )
        candidates = await self.uow.execute(
            select(
                func.count(func.distinct(col(SmsEventTable.bank_reference)))
            ).where(
                col(SmsEventTable.amount_rial) == amount_rial,
                col(SmsEventTable.sent_at) >= since,
                col(SmsEventTable.sent_at) <= until,
                col(SmsEventTable.bank_reference).is_not(None),
                ~used,
            )
        )
        competing = await self.uow.execute(
            select(func.count(col(TopupTable.id))).where(
                col(TopupTable.amount_rial) == amount_rial,
                col(TopupTable.status) == pending_status,
                col(TopupTable.id) != topup_id,
            )
        )
        return PaymentMatchFacts(
            candidates.scalar_one(), competing.scalar_one()
        )

    async def page(
        self,
        status: str | None,
        customer_id: int | None,
        q: str | None,
        offset: int,
        limit: int,
    ) -> PagedType[PaymentReviewFacts]:
        query = (
            select(PaymentReviewTable, TopupTable, CustomerTable)
            .join(
                TopupTable,
                col(TopupTable.id) == col(PaymentReviewTable.topup_id),
            )
            .join(
                CustomerTable,
                col(CustomerTable.id) == col(TopupTable.customer_id),
            )
        )
        if status is not None:
            query = query.where(col(PaymentReviewTable.status) == status)
        if customer_id is not None:
            query = query.where(col(TopupTable.customer_id) == customer_id)
        if q:
            query = query.where(
                col(CustomerTable.display_name).contains(q, autoescape=True)
            )
        count = await self.uow.execute(
            select(func.count()).select_from(query.subquery())
        )
        result = await self.uow.execute(
            query.order_by(
                col(PaymentReviewTable.checked_at).desc(),
                col(PaymentReviewTable.id).desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return PagedType(
            items=[
                PaymentReviewFacts(
                    row.PaymentReviewTable, row.TopupTable, row.CustomerTable
                )
                for row in result
            ],
            total_items=count.scalar_one(),
        )
