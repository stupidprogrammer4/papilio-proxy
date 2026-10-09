from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import case, func, select
from sqlmodel import col

from src.modules.sales.subscriptions.infra.tables import SubscriptionTable
from src.modules.sales.trials.domain.results import TrialUsage


class TrialUsageReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def read(
        self, customer_id: int, active_statuses: list[str], current: bool
    ) -> TrialUsage:
        table = SubscriptionTable
        trial = col(table.entitlement_kind) == "trial"
        query = select(
            func.coalesce(func.sum(case((trial, 1), else_=0)), 0),
            func.coalesce(
                func.sum(
                    case(
                        (
                            trial & col(table.status).in_(active_statuses),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(case((col(table.price_rial) > 0, 1), else_=0)), 0
            ),
            func.max(case((trial, col(table.created_at)), else_=None)),
        ).where(col(table.customer_id) == customer_id)
        if current:
            query = query.with_for_update()
        result = await self.uow.execute(query)
        claims, active, paid, latest = result.one()
        return TrialUsage(
            claims=claims,
            active_claims=active,
            paid_purchases=paid,
            latest_claim_at=latest,
        )
