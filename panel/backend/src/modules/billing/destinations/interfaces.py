from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.billing.destinations.domain.dtos import (
    DestinationSearch,
    DestinationWrite,
)
from src.modules.billing.destinations.domain.results import (
    DestinationDetails,
    PaymentInstruction,
)


class IPaymentDestinationService(Protocol):
    def locked(self, id: int) -> Awaitable[DestinationDetails]: ...
    def assign_receiving_alias(
        self, id: int, expected_revision: int, alias_id: int
    ) -> Awaitable[DestinationDetails]: ...

    def create(
        self, data: DestinationWrite
    ) -> Awaitable[DestinationDetails]: ...
    def update(
        self, id: int, data: DestinationWrite
    ) -> Awaitable[DestinationDetails]: ...
    def get(self, id: int) -> Awaitable[DestinationDetails]: ...
    def instruction_details(
        self, id: int
    ) -> Awaitable[DestinationDetails]: ...
    def instruction(self, id: int) -> Awaitable[PaymentInstruction]: ...
    def search(
        self, data: DestinationSearch, customer: bool = False
    ) -> Awaitable[ServicePage[DestinationDetails]]: ...
