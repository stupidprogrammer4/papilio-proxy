from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.accounts.staff.domain.results import Principal
from src.modules.billing.receipts.domain.annotations import (
    ReceiptAnnotation,
    ReceiptAnnotationWrite,
)


class IReceiptAnnotationCommand(Protocol):
    def history(
        self,
        topup_id: int,
        receipt_id: int,
        principal: Principal,
        page: int,
        per_page: int | None,
    ) -> Awaitable[ServicePage[ReceiptAnnotation]]: ...

    def append(
        self,
        topup_id: int,
        receipt_id: int,
        principal: Principal,
        data: ReceiptAnnotationWrite,
    ) -> Awaitable[ReceiptAnnotation]: ...
