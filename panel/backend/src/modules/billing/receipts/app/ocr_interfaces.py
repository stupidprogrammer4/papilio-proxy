from collections.abc import Awaitable
from typing import Protocol

from src.modules.billing.receipts.domain.extraction import ReceiptOcrResult


class ReceiptOcrRetryableError(RuntimeError):
    """The OCR provider may succeed if the event is retried later."""


class IReceiptOcrApi(Protocol):
    def recognize(self, content: bytes) -> Awaitable[ReceiptOcrResult]: ...


class IPaymentReceiptOcrCommand(Protocol):
    def process(self, receipt_id: int) -> Awaitable[None]: ...
