from papilio.infra.db.table import BaseTable
from sqlalchemy import UniqueConstraint

from src.modules.billing.receipts.domain.models import (
    PaymentReceiptAnnotationModel,
    PaymentReceiptModel,
)


class PaymentReceiptTable(PaymentReceiptModel, BaseTable, table=True):
    __table_args__ = (
        UniqueConstraint(
            "topup_id", "content_hash", name="uq_receipt_topup_content"
        ),
    )


class PaymentReceiptAnnotationTable(
    PaymentReceiptAnnotationModel, BaseTable, table=True
):
    __table_args__ = (
        UniqueConstraint(
            "receipt_id", "revision", name="uq_receipt_annotation_revision"
        ),
    )
