from papilio.infra.db.table import BaseTable

from src.modules.billing.receipts.domain.outbox_models import (
    ReceiptOcrOutboxModel,
)


class ReceiptOcrOutboxTable(ReceiptOcrOutboxModel, BaseTable, table=True):
    pass
