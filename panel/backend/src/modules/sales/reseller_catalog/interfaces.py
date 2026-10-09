from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.accounts.resellers.domain.dtos import ResellerSearch
from src.modules.sales.reseller_catalog.domain.dtos import (
    AgreementCreate,
    AgreementWrite,
)
from src.modules.sales.reseller_catalog.domain.models import (
    ResellerPlanChangeModel,
    ResellerPlanModel,
)
from src.modules.sales.reseller_catalog.domain.results import ResellerPlanQuote


class IResellerPlanCommand(Protocol):
    def create(
        self, reseller_id: int, data: AgreementCreate, staff_id: int
    ) -> Awaitable[ResellerPlanModel]: ...
    def update(
        self, reseller_id: int, id: int, data: AgreementWrite, staff_id: int
    ) -> Awaitable[ResellerPlanModel]: ...


class IResellerPlanQuery(Protocol):
    def get(
        self, reseller_id: int, id: int
    ) -> Awaitable[ResellerPlanQuote]: ...
    def search(
        self, reseller_id: int, data: ResellerSearch
    ) -> Awaitable[ServicePage[ResellerPlanQuote]]: ...
    def offered(
        self, reseller_id: int, data: ResellerSearch
    ) -> Awaitable[ServicePage[ResellerPlanQuote]]: ...


class IResellerPlanHistoryQuery(Protocol):
    def search(
        self, reseller_id: int, id: int, data: ResellerSearch
    ) -> Awaitable[ServicePage[ResellerPlanChangeModel]]: ...
