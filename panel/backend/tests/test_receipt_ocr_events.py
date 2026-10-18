import asyncio

import pytest
from faststream.exceptions import NackMessage

from src.modules.billing.receipts.domain.events import ReceiptOcrRequest
from src.modules.billing.receipts.tasks.events import ReceiptOcrConsumer

pytestmark = [pytest.mark.billing, pytest.mark.unit]


def test_retryable_provider_failure_uses_native_delayed_nack():
    class Command:
        async def process(self, receipt_id: int) -> None:
            raise RuntimeError("provider unavailable")

    async def consume() -> dict[str, object]:
        consumer = ReceiptOcrConsumer(Command())  # type: ignore[arg-type]
        with pytest.raises(NackMessage) as error:
            await consumer.run(ReceiptOcrRequest(receipt_id=41))
        return error.value.extra_options

    options = asyncio.run(consume())

    assert options == {"delay": 60}
