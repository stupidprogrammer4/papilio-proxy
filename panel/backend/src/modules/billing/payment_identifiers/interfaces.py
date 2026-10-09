from collections.abc import Awaitable
from typing import Protocol

from src.modules.billing.payment_identifiers.domain.contracts import (
    PaymentAmountAllocation,
    PaymentIdentifierPolicy,
)
from src.modules.billing.payment_identifiers.domain.models import (
    PaymentAmountReservationModel,
)


class IPaymentAmountAllocationQuery(Protocol):
    def allocate(
        self,
        requested: int,
        realm_id: int,
        policy: PaymentIdentifierPolicy,
        maximum_topup_rial: int,
    ) -> Awaitable[PaymentAmountAllocation]: ...


class IPaymentAmountReservationService(Protocol):
    def create(
        self, data: PaymentAmountReservationModel
    ) -> Awaitable[PaymentAmountReservationModel]: ...
