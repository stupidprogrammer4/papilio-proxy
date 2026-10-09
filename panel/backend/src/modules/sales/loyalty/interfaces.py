from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.sales.loyalty.domain.dtos import (
    CustomerTierWrite,
    LoyaltyPolicyWrite,
    LoyaltySearch,
)
from src.modules.sales.loyalty.domain.models import CustomerTierModel
from src.modules.sales.loyalty.domain.results import (
    CustomerPriceQuote,
    CustomerTierRead,
    LoyaltyPolicyRead,
)


class ICustomerTierService(Protocol):
    def initialize(self) -> Awaitable[None]: ...
    def create(
        self, data: CustomerTierWrite
    ) -> Awaitable[CustomerTierModel]: ...
    def update(
        self, id: int, data: CustomerTierWrite
    ) -> Awaitable[CustomerTierModel]: ...
    def search(
        self, data: LoyaltySearch
    ) -> Awaitable[ServicePage[CustomerTierModel]]: ...
    def candidates(
        self, *, locked: bool = False
    ) -> Awaitable[list[CustomerTierModel]]: ...


class ILoyaltyPolicyService(Protocol):
    def initialize(self) -> Awaitable[None]: ...
    def current(
        self, *, locked: bool = False
    ) -> Awaitable[LoyaltyPolicyRead]: ...
    def update(
        self, data: LoyaltyPolicyWrite
    ) -> Awaitable[LoyaltyPolicyRead]: ...


class ICustomerLoyaltyQuery(Protocol):
    def status(
        self, customer_id: int, *, locked: bool = False
    ) -> Awaitable[CustomerTierRead]: ...
    def quote(
        self,
        customer_id: int,
        plan_id: int,
        *,
        renewal: bool = False,
        locked: bool = False,
    ) -> Awaitable[CustomerPriceQuote]: ...


class IPurchaseVolumeCommand(Protocol):
    def record(
        self,
        customer_id: int,
        subscription_id: int,
        generation: int,
        plan_id: int,
        quota_bytes: int | None,
        paid_rial: int,
        commerce: CustomerPriceQuote | None = None,
    ) -> Awaitable[None]: ...
    def reverse(
        self, subscription_id: int, generation: int
    ) -> Awaitable[None]: ...


class ILoyaltyInitializeCommand(Protocol):
    def initialize(self) -> Awaitable[LoyaltyPolicyRead]: ...
