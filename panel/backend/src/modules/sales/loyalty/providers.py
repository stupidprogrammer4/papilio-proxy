from dishka import Provider, Scope, provide

from src.modules.sales.loyalty.app.commands import PurchaseVolumeCommand
from src.modules.sales.loyalty.app.initialize import LoyaltyInitializeCommand
from src.modules.sales.loyalty.app.queries import CustomerLoyaltyQuery
from src.modules.sales.loyalty.app.services import (
    CustomerTierService,
    LoyaltyPolicyService,
)
from src.modules.sales.loyalty.infra.mysql import (
    CustomerTierRepository,
    LoyaltyPolicyRepository,
    PurchaseVolumeRepository,
)
from src.modules.sales.loyalty.infra.readers import (
    CustomerPurchaseVolumeReader,
)
from src.modules.sales.loyalty.interfaces import (
    ICustomerLoyaltyQuery,
    ICustomerTierService,
    ILoyaltyInitializeCommand,
    ILoyaltyPolicyService,
    IPurchaseVolumeCommand,
)


class LoyaltyProvider(Provider):
    scope = Scope.REQUEST
    tiers = provide(CustomerTierRepository)
    policy = provide(LoyaltyPolicyRepository)
    volumes = provide(PurchaseVolumeRepository)
    reader = provide(CustomerPurchaseVolumeReader)
    tier_service = provide(CustomerTierService, provides=ICustomerTierService)
    policy_service = provide(
        LoyaltyPolicyService, provides=ILoyaltyPolicyService
    )
    query = provide(CustomerLoyaltyQuery, provides=ICustomerLoyaltyQuery)
    command = provide(PurchaseVolumeCommand, provides=IPurchaseVolumeCommand)
    initialize = provide(
        LoyaltyInitializeCommand, provides=ILoyaltyInitializeCommand
    )
