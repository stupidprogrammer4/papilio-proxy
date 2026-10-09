from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.sales.catalog.domain.bundles import (
    PlanConfigurationRead,
    PlanConfigurationSearch,
)
from src.modules.sales.catalog.domain.dtos import (
    PlanCreate,
    PlanSearch,
    PlanSetActive,
    PlanUpdate,
)
from src.modules.sales.catalog.domain.models import PlanModel
from src.modules.sales.catalog.domain.results import PlanPolicyDefaults


class IPlanService(Protocol):
    def get_active(self, id: int) -> Awaitable[PlanModel]: ...
    def policy_defaults(self) -> Awaitable[PlanPolicyDefaults]: ...
    def create(self, data: PlanCreate) -> Awaitable[PlanModel]: ...
    def update(self, id: int, data: PlanUpdate) -> Awaitable[PlanModel]: ...
    def set_active(
        self, id: int, data: PlanSetActive
    ) -> Awaitable[PlanModel]: ...
    def get(self, id: int) -> Awaitable[PlanModel]: ...
    def search(
        self, data: PlanSearch
    ) -> Awaitable[ServicePage[PlanModel]]: ...


class IPlanConfigurationQuery(Protocol):
    def search(
        self, plan_id: int, data: PlanConfigurationSearch, public: bool = False
    ) -> Awaitable[ServicePage[PlanConfigurationRead]]: ...
