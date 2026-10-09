from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.billing.receipts.domain.results import (
    ReceiptDetails,
    ReceiptDownload,
)


class IPaymentReceiptCommand(Protocol):
    def upload(
        self, topup_id: int, customer_id: int | None, content: bytes
    ) -> Awaitable[ReceiptDetails]: ...
    def search(
        self,
        topup_id: int,
        customer_id: int | None,
        page: int,
        per_page: int | None,
    ) -> Awaitable[ServicePage[ReceiptDetails]]: ...
    def download(
        self, topup_id: int, id: int, customer_id: int | None
    ) -> Awaitable[ReceiptDownload]: ...
