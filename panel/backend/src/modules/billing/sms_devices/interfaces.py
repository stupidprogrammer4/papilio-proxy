from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.billing.sms.domain.dtos import SmsReceived
from src.modules.billing.sms_devices.domain.dtos import (
    SmsDeviceSearch,
    SmsDeviceWrite,
)
from src.modules.billing.sms_devices.domain.results import (
    SmsDeviceEnrollment,
    SmsDeviceRead,
)


class ISmsDeviceService(Protocol):
    def get(self, id: int) -> Awaitable[SmsDeviceRead]: ...
    def create(
        self, data: SmsDeviceWrite
    ) -> Awaitable[SmsDeviceEnrollment]: ...
    def update(
        self, id: int, data: SmsDeviceWrite
    ) -> Awaitable[SmsDeviceRead]: ...
    def rotate(
        self, id: int, expected_revision: int
    ) -> Awaitable[SmsDeviceEnrollment]: ...
    def search(
        self, data: SmsDeviceSearch
    ) -> Awaitable[ServicePage[SmsDeviceRead]]: ...
    def verify(
        self,
        id: int,
        timestamp: str,
        signature: str,
        raw: bytes,
        sms: SmsReceived,
    ) -> Awaitable[None]: ...


class ISmsSettlementCommand(Protocol):
    def check_event(self, event_id: str) -> Awaitable[str]: ...
    def check_topup(self, topup_id: int) -> Awaitable[str]: ...
    def approved_topup_for_event(
        self, event_id: str, device_id: int
    ) -> Awaitable[int | None]: ...
