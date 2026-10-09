from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import case, exists, func, select
from sqlmodel import col

from src.modules.sales.loyalty.domain.results import (
    CustomerPurchaseVolumeFacts,
)
from src.modules.sales.loyalty.infra.tables import PurchaseVolumeTable
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable


class CustomerPurchaseVolumeReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def totals(
        self,
        customer_id: int,
        positive: int,
        entitlement_kind: str,
        excluded_statuses: list[str],
        locked: bool,
        minimum_paid_rial: int,
    ) -> CustomerPurchaseVolumeFacts:
        query = select(
            func.coalesce(func.sum(col(PurchaseVolumeTable.volume_bytes)), 0),
            func.coalesce(
                func.sum(
                    case(
                        (
                            col(PurchaseVolumeTable.volume_bytes) > positive,
                            col(PurchaseVolumeTable.volume_bytes),
                        ),
                        else_=positive,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(col(PurchaseVolumeTable.purchase_count)), 0
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            col(PurchaseVolumeTable.purchase_count) > positive,
                            col(PurchaseVolumeTable.purchase_count),
                        ),
                        else_=positive,
                    )
                ),
                0,
            ),
        ).where(col(PurchaseVolumeTable.customer_id) == customer_id)
        if locked:
            query = query.with_for_update()
        volume = await self.uow.execute(query)
        recorded = exists(
            select(col(PurchaseVolumeTable.id)).where(
                col(PurchaseVolumeTable.subscription_id)
                == col(SubscriptionTable.id)
            )
        )
        legacy = await self.uow.execute(
            select(func.count(col(SubscriptionTable.id))).where(
                col(SubscriptionTable.customer_id) == customer_id,
                col(SubscriptionTable.entitlement_kind) == entitlement_kind,
                col(SubscriptionTable.status).not_in(excluded_statuses),
                ~recorded,
                col(SubscriptionTable.price_rial) >= minimum_paid_rial,
            )
        )
        net, lifetime, purchases, lifetime_purchases = volume.one()
        return CustomerPurchaseVolumeFacts(
            int(net),
            int(lifetime),
            int(purchases),
            int(lifetime_purchases),
            int(legacy.scalar_one()),
        )
