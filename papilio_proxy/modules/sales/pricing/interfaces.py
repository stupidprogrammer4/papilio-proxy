from typing import Protocol

from papilio_proxy.modules.sales.pricing.domain.entities import PricingAssumptions


class PricingRepository(Protocol):
    async def get(self) -> PricingAssumptions | None: ...
    async def save(self, value: PricingAssumptions) -> None: ...
