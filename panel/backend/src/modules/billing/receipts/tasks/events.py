from typing import ClassVar

from faststream import AckPolicy
from faststream.exceptions import NackMessage
from faststream.nats import JStream, PullSub
from nats.js.api import AckPolicy as JetStreamAckPolicy
from nats.js.api import ConsumerConfig, RetentionPolicy
from papilio_tasks.apps.events.publishers.jetstream import JetPublisher
from papilio_tasks.apps.events.subscribers.jetstream import JetSubscriber

from src.modules.billing.receipts.app.ocr_interfaces import (
    IPaymentReceiptOcrCommand,
)
from src.modules.billing.receipts.domain.events import ReceiptOcrRequest


class ReceiptOcrRequested(JetPublisher[ReceiptOcrRequest]):
    subject: ClassVar[str] = "billing.receipts.ocr.requested"
    stream: ClassVar[JStream] = JStream(
        "receipt-ocr",
        subjects=[subject],
        retention=RetentionPolicy.WORK_QUEUE,
    )


class ReceiptOcrConsumer(JetSubscriber[ReceiptOcrRequest]):
    publisher = ReceiptOcrRequested
    durable: ClassVar[str | None] = "receipt-ocr-v1"
    pull_sub: ClassVar[bool | PullSub] = PullSub(batch_size=1, timeout=1)
    config: ClassVar[ConsumerConfig | None] = ConsumerConfig(
        ack_policy=JetStreamAckPolicy.EXPLICIT,
        ack_wait=60,
        max_deliver=-1,
        backoff=[60, 300, 1800],
    )
    ack_policy: ClassVar[AckPolicy | None] = AckPolicy.NACK_ON_ERROR

    def __init__(self, command: IPaymentReceiptOcrCommand) -> None:
        self.command = command

    async def run(self, event: ReceiptOcrRequest) -> None:
        try:
            await self.command.process(event.receipt_id)
        except Exception as error:
            raise NackMessage(delay=60) from error
