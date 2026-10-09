from papilio.infra.db.table import BaseTable
from sqlalchemy import Index

from src.modules.sales.checkout.domain.attempts import CheckoutAttemptModel
from src.modules.sales.checkout.domain.models import (
    CheckoutActionReceiptModel,
    CheckoutIntentModel,
)


class CheckoutIntentTable(CheckoutIntentModel, BaseTable, table=True):
    __table_args__ = (Index("ix_checkout_due", "state", "checked_at", "id"),)


class CheckoutActionReceiptTable(
    CheckoutActionReceiptModel, BaseTable, table=True
):
    pass


class CheckoutAttemptTable(CheckoutAttemptModel, BaseTable, table=True):
    pass
