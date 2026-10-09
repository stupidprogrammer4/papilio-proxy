from collections.abc import Awaitable
from typing import Protocol

from src.modules.network.qr_codes.domain.dtos import QrImage


class ISubscriptionQrQuery(Protocol):
    def feed(self, token: str) -> Awaitable[QrImage]: ...

    def profile(
        self, token: str, profile_id: int, host_id: int | None
    ) -> Awaitable[QrImage]: ...
