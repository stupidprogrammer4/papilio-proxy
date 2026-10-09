from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.billing.sms.domain.dtos import SmsReceived, SmsSearch
from src.modules.billing.sms.domain.models import SmsEventModel


class ISmsService(Protocol):
    def get(self, id: int) -> Awaitable[SmsEventModel]: ...
    def receive(
        self, data: SmsReceived, *, device_id: int | None = None
    ) -> Awaitable[SmsEventModel]: ...
    def search(
        self, data: SmsSearch
    ) -> Awaitable[ServicePage[SmsEventModel]]: ...


class ISmsCandidateQuery(Protocol):
    def for_topup(
        self, topup_id: int, page: int, per_page: int | None
    ) -> Awaitable[ServicePage[SmsEventModel]]: ...
