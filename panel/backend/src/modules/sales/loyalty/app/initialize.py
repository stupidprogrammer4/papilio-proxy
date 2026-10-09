from papilio.infra.db.tools.decorators import transactional

from src.modules.sales.loyalty.domain.results import LoyaltyPolicyRead
from src.modules.sales.loyalty.interfaces import (
    ICustomerTierService,
    ILoyaltyPolicyService,
)


class LoyaltyInitializeCommand:
    def __init__(
        self, tiers: ICustomerTierService, policies: ILoyaltyPolicyService
    ) -> None:
        self.tiers, self.policies = tiers, policies

    @transactional
    async def initialize(self) -> LoyaltyPolicyRead:
        await self.policies.initialize()
        await self.tiers.initialize()
        result = await self.policies.current()
        return result
