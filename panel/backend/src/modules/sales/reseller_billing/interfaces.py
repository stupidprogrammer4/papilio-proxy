from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.accounts.resellers.domain.results import ResellerPrincipal
from src.modules.sales.catalog.domain.dtos import PlanSearch
from src.modules.sales.catalog.domain.models import PlanModel
from src.modules.sales.reseller_billing.domain.dtos import PurchaseActor
from src.modules.sales.reseller_billing.domain.results import (
    PurchaseBilling,
    RenewalBilling,
)
from src.modules.sales.subscriptions.domain.dtos import (
    SubscriptionCreate,
    SubscriptionSearch,
)
from src.modules.sales.subscriptions.domain.models import SubscriptionModel


class IResellerBillingQuery(Protocol):
    def purchase(
        self, data: SubscriptionCreate, actor: PurchaseActor | None
    ) -> Awaitable[PurchaseBilling | None]: ...
    def replay(
        self, subscription: SubscriptionModel, actor: PurchaseActor | None
    ) -> Awaitable[None]: ...
    def renewal(
        self, subscription: SubscriptionModel
    ) -> Awaitable[RenewalBilling | None]: ...
    def customer_renewal_choice(
        self, subscription: SubscriptionModel, enabled: bool
    ) -> Awaitable[None]: ...
    def reseller_renewal_choice(
        self, subscription: SubscriptionModel, principal: ResellerPrincipal
    ) -> Awaitable[None]: ...


class IResellerSubscriptionQuery(Protocol):
    def get(
        self, reseller_id: int, id: int
    ) -> Awaitable[SubscriptionModel]: ...
    def search(
        self, reseller_id: int, data: SubscriptionSearch
    ) -> Awaitable[ServicePage[SubscriptionModel]]: ...


class ICustomerCatalogQuery(Protocol):
    def search(
        self, customer_id: int, data: PlanSearch
    ) -> Awaitable[ServicePage[PlanModel]]: ...
    def get(self, customer_id: int, plan_id: int) -> Awaitable[PlanModel]: ...
