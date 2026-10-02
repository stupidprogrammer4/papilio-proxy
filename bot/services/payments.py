from __future__ import annotations

from enum import StrEnum
from typing import Protocol
from uuid import UUID

from bot.models.payments import PaymentInitiation, PaymentProviderUnavailable, ProviderVerification


class PaymentVerifier(Protocol):
    async def verify(self, authority: str) -> ProviderVerification: ...


class ReceiptAutomation(Protocol):
    async def recheck_uploaded(self) -> int: ...


class PaymentRepository(Protocol):
    async def order_id_for_authority(self, authority: str) -> str | None: ...

    async def pending_authorities(self, after: str | None, limit: int) -> list[str]: ...

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

    def __init__(self, provider: PaymentVerifier, repository: PaymentRepository,
                 receipts: ReceiptAutomation | None = None) -> None:
        self._provider = provider
        self._repository = repository
        self._cursor: str | None = None
        self._receipts = receipts

    async def return_order_id(self, authority: str) -> str | None:
        value = await self._repository.order_id_for_authority(authority)
        if not isinstance(value, str):
            return None
        try:
            return str(UUID(value))
        except ValueError:
            return None

    async def recheck_pending(self, limit: int = 5) -> int:
        """Recover payments even when the buyer never opens the callback URL."""
        receipt_paid = await self._receipts.recheck_uploaded() if self._receipts else 0
        authorities = await self._repository.pending_authorities(self._cursor, limit)
        if not authorities and self._cursor:
            self._cursor = None
            authorities = await self._repository.pending_authorities(None, limit)
        paid = receipt_paid
        for authority in authorities:
            self._cursor = authority
            try:
                paid += await self.verify_callback(authority) == CallbackOutcome.PAID
            except (PaymentProviderUnavailable, PaymentSettlementError):
                # Do not expose the authority; leave the durable attempt retryable.
                continue
        return paid

    async def verify_callback(self, authority: str) -> CallbackOutcome:
        if not await self._repository.has_authority(authority):
            raise PaymentSettlementError("KPay authority is not bound to an order")
        result = await self._provider.verify(authority)
        if not result.verified:
            return CallbackOutcome.NOT_PAID
        if not await self._repository.settle_verified(result):
            raise PaymentSettlementError("KPay authority is not bound to an order")
        return CallbackOutcome.PAID
