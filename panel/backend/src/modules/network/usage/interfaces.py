from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.network.usage.domain.dtos import (
    UsageAllocation,
    UsageReport,
    UsageSearch,
)
from src.modules.network.usage.domain.models import (
    UsageEventModel,
    UsageGrantModel,
)
from src.modules.network.usage.domain.results import UsageSummary


class IUsageCommand(Protocol):
    async def allocate(
        self, code: str, key: str, data: UsageAllocation
    ) -> UsageGrantModel: ...
    async def report(
        self, code: str, key: str, grant_id: int, data: UsageReport
    ) -> UsageEventModel: ...


class IUsageQuery(Protocol):
    async def grants(
        self, data: UsageSearch
    ) -> ServicePage[UsageGrantModel]: ...
    async def events(
        self, data: UsageSearch
    ) -> ServicePage[UsageEventModel]: ...
    async def summary(self, data: UsageSearch) -> UsageSummary: ...
    async def has_open_profile(
        self, profile_id: int, generation: int
    ) -> bool: ...
