from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.accounts.customers.domain.dtos import (
    CustomerAccessSearch,
    CustomerAccessWrite,
    CustomerCreate,
    CustomerProfileWrite,
    CustomerSearch,
)
from src.modules.accounts.customers.domain.models import (
    CustomerAccessChangeModel,
    CustomerModel,
)
from src.modules.accounts.resellers.domain.dtos import (
    ResellerAccountCreate,
    ResellerAccountWrite,
    ResellerCreate,
    ResellerCredentials,
    ResellerDefaults,
    ResellerPasswordWrite,
    ResellerSearch,
    ResellerWrite,
)
from src.modules.accounts.resellers.domain.models import (
    ResellerAccountChangeModel,
    ResellerAccountModel,
    ResellerChangeModel,
    ResellerModel,
)
from src.modules.accounts.resellers.domain.results import (
    CreatedReseller,
    IssuedResellerSession,
    ResellerAccountActor,
    ResellerPrincipal,
)


class IResellerRegistryCommand(Protocol):
    def create(
        self, data: ResellerCreate, staff_id: int
    ) -> Awaitable[CreatedReseller]: ...
    def update(
        self, id: int, data: ResellerWrite, staff_id: int
    ) -> Awaitable[ResellerModel]: ...


class IResellerRegistryQuery(Protocol):
    def defaults(self) -> Awaitable[ResellerDefaults]: ...
    def get(self, id: int) -> Awaitable[ResellerModel]: ...
    def locked(self, id: int) -> Awaitable[ResellerModel]: ...
    def search(
        self, data: ResellerSearch
    ) -> Awaitable[ServicePage[ResellerModel]]: ...


class IResellerRegistryHistoryQuery(Protocol):
    def search(
        self, reseller_id: int, data: ResellerSearch
    ) -> Awaitable[ServicePage[ResellerChangeModel]]: ...


class IResellerAuthCommand(Protocol):
    def login(
        self, data: ResellerCredentials
    ) -> Awaitable[IssuedResellerSession]: ...
    def logout(self, token: str) -> Awaitable[None]: ...


class IResellerAuthQuery(Protocol):
    def current(self, token: str) -> Awaitable[ResellerPrincipal]: ...


class IResellerAccountCommand(Protocol):
    def create(
        self,
        reseller_id: int,
        data: ResellerAccountCreate,
        actor: ResellerAccountActor,
    ) -> Awaitable[ResellerAccountModel]: ...
    def update(
        self,
        reseller_id: int,
        id: int,
        data: ResellerAccountWrite,
        actor: ResellerAccountActor,
    ) -> Awaitable[ResellerAccountModel]: ...
    def reset_password(
        self,
        reseller_id: int,
        id: int,
        data: ResellerPasswordWrite,
        actor: ResellerAccountActor,
    ) -> Awaitable[ResellerAccountModel]: ...


class IResellerAccountQuery(Protocol):
    def get(
        self, reseller_id: int, id: int
    ) -> Awaitable[ResellerAccountModel]: ...
    def search(
        self, reseller_id: int, data: ResellerSearch
    ) -> Awaitable[ServicePage[ResellerAccountModel]]: ...


class IResellerAccountHistoryQuery(Protocol):
    def search(
        self, reseller_id: int, account_id: int, data: ResellerSearch
    ) -> Awaitable[ServicePage[ResellerAccountChangeModel]]: ...


class IResellerCustomerCommand(Protocol):
    def update_access(
        self, principal: ResellerPrincipal, id: int, data: CustomerAccessWrite
    ) -> Awaitable[CustomerModel]: ...

    def create(
        self, principal: ResellerPrincipal, data: CustomerCreate
    ) -> Awaitable[CustomerModel]: ...
    def update_profile(
        self, principal: ResellerPrincipal, id: int, data: CustomerProfileWrite
    ) -> Awaitable[CustomerModel]: ...


class IResellerCustomerQuery(Protocol):
    def access_history(
        self, reseller_id: int, customer_id: int, data: CustomerAccessSearch
    ) -> Awaitable[ServicePage[CustomerAccessChangeModel]]: ...

    def get(
        self, reseller_id: int, customer_id: int
    ) -> Awaitable[CustomerModel]: ...
    def search(
        self, reseller_id: int, data: CustomerSearch
    ) -> Awaitable[ServicePage[CustomerModel]]: ...
