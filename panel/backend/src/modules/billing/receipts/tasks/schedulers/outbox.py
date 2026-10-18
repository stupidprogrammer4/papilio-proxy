from papilio_tasks.apps.schedulers.backends.redis import RedisScheduler

from src.modules.billing.receipts.app.outbox_interfaces import (
    IPaymentReceiptOutboxCommand,
)


class PublishReceiptOcrOutbox(RedisScheduler):
    schedule = [{"interval": 5, "schedule_id": "receipt-ocr-outbox"}]

    def __init__(self, command: IPaymentReceiptOutboxCommand) -> None:
        self.command = command

    async def run(self) -> bool:
        published = await self.command.publish_next()
        return published
