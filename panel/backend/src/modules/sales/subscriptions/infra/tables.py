from papilio.infra.db.table import BaseTable
from sqlalchemy import Index

from src.modules.sales.subscriptions.domain.models import (
    SubscriptionControlModel,
    SubscriptionModel,
)


class SubscriptionTable(SubscriptionModel, BaseTable, table=True):
    __table_args__ = (
        Index(
            "ix_subscription_renewal_scan",
            "auto_renew",
            "status",
            "expires_at",
        ),
    )


class SubscriptionControlTable(
    SubscriptionControlModel, BaseTable, table=True
):
    table_name = "tbl_subscription_controls"
