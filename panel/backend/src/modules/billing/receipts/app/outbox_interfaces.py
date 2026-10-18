from collections.abc import Awaitable
from typing import Protocol


class IReceiptOcrEventPublisher(Protocol):
    def publish(self, receipt_id: int) -> Awaitable[None]: ...


class IPaymentReceiptOutboxCommand(Protocol):
    def publish_next(self) -> Awaitable[bool]: ...
