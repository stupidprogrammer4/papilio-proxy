from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.accounts.resellers.domain.results import ResellerPrincipal
from src.modules.sales.reseller_billing.domain.dtos import PurchaseActor
from src.modules.sales.subscriptions.domain.dtos import (
    AutoRenewChoice,
    ProvisionFailure,
    SubscriptionControlSearch,
    SubscriptionCreate,
    SubscriptionResume,
    SubscriptionSearch,
    SubscriptionSuspend,
)
from src.modules.sales.subscriptions.domain.models import (
    SubscriptionControlModel,
    SubscriptionModel,
)
from src.modules.sales.subscriptions.domain.results import (
    SubscriptionRenewalQuote,
    SubscriptionUsageUpdate,
)


class ISubscriptionRenewalQuoteQuery(Protocol):
    def get(
        self, subscription: SubscriptionModel, *, locked: bool = False
    ) -> Awaitable[SubscriptionRenewalQuote]: ...


class ISubscriptionCommand(Protocol):
    def get(self, id: int) -> Awaitable[SubscriptionModel]: ...
    def purchase(
        self, data: SubscriptionCreate, *, actor: PurchaseActor | None = None
    ) -> Awaitable[SubscriptionModel]: ...
    def set_auto_renew(
        self, id: int, data: AutoRenewChoice
    ) -> Awaitable[SubscriptionModel]: ...
    def customer_set_auto_renew(
        self, id: int, customer_id: int, data: AutoRenewChoice
    ) -> Awaitable[SubscriptionModel]: ...
    def reseller_set_auto_renew(
        self, id: int, principal: ResellerPrincipal, data: AutoRenewChoice
    ) -> Awaitable[SubscriptionModel]: ...
    def fail_provision(
        self, id: int, data: ProvisionFailure, staff_id: int
    ) -> Awaitable[SubscriptionModel]: ...
    def renew_due(self, id: int) -> Awaitable[SubscriptionModel]: ...
    def search(
        self, data: SubscriptionSearch
    ) -> Awaitable[ServicePage[SubscriptionModel]]: ...


class ISubscriptionBatchService(Protocol):
    def locked_many(
        self, ids: list[int]
    ) -> Awaitable[list[SubscriptionModel]]: ...
    def update_used_many(
        self, updates: list[SubscriptionUsageUpdate]
    ) -> Awaitable[None]: ...


class IRenewalQuery(Protocol):
    def due_ids(self) -> Awaitable[list[int]]: ...


class ISubscriptionLifecycleCommand(Protocol):
    def check(self, id: int) -> Awaitable[SubscriptionModel]: ...


class ISubscriptionLifecycleQuery(Protocol):
    def due_ids(self) -> Awaitable[list[int]]: ...


class ISubscriptionControlCommand(Protocol):
    def suspend(
        self, id: int, data: SubscriptionSuspend, staff_id: int
    ) -> Awaitable[SubscriptionModel]: ...
    def resume(
        self, id: int, data: SubscriptionResume, staff_id: int
    ) -> Awaitable[SubscriptionModel]: ...


class ISubscriptionControlQuery(Protocol):
    def search(
        self, subscription_id: int, data: SubscriptionControlSearch
    ) -> Awaitable[ServicePage[SubscriptionControlModel]]: ...


class ICustomerHoldCommand(Protocol):
    def check(self, subscription_id: int) -> Awaitable[SubscriptionModel]: ...


class ICustomerHoldQuery(Protocol):
    def due_ids(self) -> Awaitable[list[int]]: ...


class ICustomerHoldFinalizeCommand(Protocol):
    def check(self, customer_id: int) -> Awaitable[bool]: ...


class ICustomerHoldFinalizeQuery(Protocol):
    def due_ids(self) -> Awaitable[list[int]]: ...
