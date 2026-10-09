from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.accounts.customers.domain.configurations import (
    CustomerConfigurationRead,
    CustomerConfigurationSearch,
)
from src.modules.accounts.customers.domain.dtos import (
    CustomerAccessSearch,
    CustomerAccessState,
    CustomerAccessWrite,
    CustomerCreate,
    CustomerProfileWrite,
    CustomerSearch,
)
from src.modules.accounts.customers.domain.models import (
    CustomerAccessChangeModel,
    CustomerModel,
)
from src.modules.accounts.customers.domain.results import CustomerAccessActor


class ICustomerService(Protocol):
    def creation_access(self) -> Awaitable[CustomerAccessState]: ...
    def create(self, data: CustomerCreate) -> Awaitable[CustomerModel]: ...
    def update_profile(
        self, id: int, data: CustomerProfileWrite
    ) -> Awaitable[CustomerModel]: ...
    def locked(self, id: int) -> Awaitable[CustomerModel]: ...
    def locked_many(
        self, ids: list[int]
    ) -> Awaitable[list[CustomerModel]]: ...
    def get(self, id: int) -> Awaitable[CustomerModel]: ...
    def ensure_telegram(
        self, telegram_id: int, display_name: str
    ) -> Awaitable[CustomerModel]: ...
    def search(
        self, data: CustomerSearch
    ) -> Awaitable[ServicePage[CustomerModel]]: ...


class ICustomerAccessCommand(Protocol):
    def update(
        self, id: int, data: CustomerAccessWrite, actor: CustomerAccessActor
    ) -> Awaitable[CustomerModel]: ...


class ICustomerAccessQuery(Protocol):
    def search(
        self, customer_id: int, data: CustomerAccessSearch
    ) -> Awaitable[ServicePage[CustomerAccessChangeModel]]: ...


class ICustomerConfigurationQuery(Protocol):
    def search(
        self, customer_id: int, data: CustomerConfigurationSearch
    ) -> Awaitable[ServicePage[CustomerConfigurationRead]]: ...
