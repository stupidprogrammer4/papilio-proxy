from __future__ import annotations

from typing import Protocol

from bot.models.payments import ProviderVerification


class PaymentVerifier(Protocol):
    async def verify(self, authority: str) -> ProviderVerification: ...


class PaymentVerificationService:
    """Only observes provider state; order matching and fulfillment are separate work."""

    def __init__(self, provider: PaymentVerifier) -> None:
        self._provider = provider

    async def verify_callback(self, authority: str) -> ProviderVerification:
        return await self._provider.verify(authority)
