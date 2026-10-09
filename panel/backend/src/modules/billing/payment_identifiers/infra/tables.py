from papilio.infra.db.table import BaseTable
from sqlalchemy import UniqueConstraint

from src.modules.billing.payment_identifiers.domain.models import (
    PaymentAmountReservationModel,
)


class PaymentAmountReservationTable(
    PaymentAmountReservationModel, BaseTable, table=True
):
    __table_args__ = (
        UniqueConstraint(
            "receiving_realm_id",
            "payable_amount_rial",
            name="uq_payment_reserved_realm_amount",
        ),
    )
