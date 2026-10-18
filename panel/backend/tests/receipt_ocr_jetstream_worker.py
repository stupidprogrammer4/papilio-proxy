import asyncio
import sys
from pathlib import Path
from typing import ClassVar

from dishka import Provider, Scope, provide
from faststream import AckPolicy
from faststream.nats import NatsBroker as NativeNatsBroker
from faststream.nats import PullSub
from nats.js.api import AckPolicy as JetStreamAckPolicy
from nats.js.api import ConsumerConfig
from papilio_tasks.apps.events.application import create_app
from papilio_tasks.apps.events.registry.jetstream import JetRegistrar
from papilio_tasks.infra.faststream.brokers.backends.nats import NatsBroker

from src.modules.billing.receipts.app.ocr_interfaces import (
    IPaymentReceiptOcrCommand,
)
from src.modules.billing.receipts.tasks.events import (
    ReceiptOcrConsumer,
    ReceiptOcrRequested,
)


class RecoveryConsumer(ReceiptOcrConsumer):
    publisher = ReceiptOcrRequested
    durable: ClassVar[str | None] = "receipt-ocr-kill-test"
    pull_sub: ClassVar[bool | PullSub] = PullSub(batch_size=1, timeout=1)
    config: ClassVar[ConsumerConfig | None] = ConsumerConfig(
        ack_policy=JetStreamAckPolicy.EXPLICIT,
        ack_wait=1,
        max_deliver=-1,
    )
    ack_policy: ClassVar[AckPolicy | None] = AckPolicy.NACK_ON_ERROR


class RecordingCommand:
    def __init__(self, result_path: Path, block: bool) -> None:
        self.result_path = result_path
        self.block = block

    async def process(self, receipt_id: int) -> None:
        await asyncio.to_thread(
            self.result_path.write_text, str(receipt_id), encoding="utf-8"
        )
        if self.block:
            await asyncio.Event().wait()


class WorkerProvider(Provider):
    def __init__(self, result_path: Path, block: bool) -> None:
        super().__init__()
        self.result_path = result_path
        self.block = block

    @provide(scope=Scope.APP)
    def command(self) -> IPaymentReceiptOcrCommand:
        return RecordingCommand(self.result_path, self.block)

    consumer = provide(RecoveryConsumer, scope=Scope.REQUEST)


def main() -> None:
    url, output, mode = sys.argv[1:]
    broker = NatsBroker(NativeNatsBroker(url))
    registrar = JetRegistrar(broker)
    registrar.publisher(ReceiptOcrRequested)
    registrar.subscriber(RecoveryConsumer)
    app = create_app(
        registrar=registrar,
        providers=[WorkerProvider(Path(output), mode == "block")],
    )

    async def serve() -> None:
        await app.start()
        await asyncio.Event().wait()

    asyncio.run(serve())


if __name__ == "__main__":
    main()
