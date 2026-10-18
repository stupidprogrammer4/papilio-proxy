from src.modules.billing.receipts.app.outbox_interfaces import (
    IReceiptOcrEventPublisher,
)
from src.modules.billing.receipts.domain.events import ReceiptOcrRequest
from src.modules.billing.receipts.tasks.events import ReceiptOcrRequested


class JetStreamReceiptOcrEventPublisher(IReceiptOcrEventPublisher):
    async def publish(self, receipt_id: int) -> None:
        event = ReceiptOcrRequest(receipt_id=receipt_id)
        await ReceiptOcrRequested.publish(event)
