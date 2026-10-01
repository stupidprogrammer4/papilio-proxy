from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from bot.models.payments import PaymentInitiation, ProviderVerification


class PaymentVerifier(Protocol):
    async def verify(self, authority: str) -> ProviderVerification: ...


class PaymentRepository(Protocol):
    async def has_authority(self, authority: str) -> bool: ...

    async def attach_checkout(self, order_id: str, checkout: PaymentInitiation) -> None: ...

    async def settle_verified(self, result: ProviderVerification) -> bool: ...


class PaymentSettlementError(RuntimeError):
    """Payment cannot safely be associated with the expected order."""


class CallbackOutcome(StrEnum):
    NOT_PAID = "not_paid"
    PAID = "paid"


class PaymentVerificationService:
    """Rechecks KPay and atomically records settled-but-unprovisioned orders."""

    def __init__(self, provider: PaymentVerifier, repository: PaymentRepository) -> None:
        self._provider = provider
        self._repository = repository

    async def verify_callback(self, authority: str) -> CallbackOutcome:
        if not await self._repository.has_authority(authority):
            raise PaymentSettlementError("KPay authority is not bound to an order")
        result = await self._provider.verify(authority)
        if not result.verified:
            return CallbackOutcome.NOT_PAID
        if not await self._repository.settle_verified(result):
            raise PaymentSettlementError("KPay authority is not bound to an order")
        return CallbackOutcome.PAID
