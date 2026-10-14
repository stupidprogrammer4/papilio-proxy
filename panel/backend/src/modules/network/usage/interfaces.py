from collections.abc import Awaitable
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
from src.modules.network.usage.domain.results import (
    ProfileUsageAssignment,
    UsageEventIdentity,
    UsageGenerationKey,
    UsageGrantAllocationKey,
    UsageProfileGenerationKey,
    UsageReservationTotal,
    UsageSummary,
)


class IUsageGrantService(Protocol):
    def locked(self, id: int) -> Awaitable[UsageGrantModel | None]: ...
    def locked_many(
        self, ids: list[int]
    ) -> Awaitable[list[UsageGrantModel]]: ...
    def allocation_many(
        self, keys: list[UsageGrantAllocationKey]
    ) -> Awaitable[list[UsageGrantModel]]: ...
    def create(self, data: UsageGrantModel) -> Awaitable[UsageGrantModel]: ...
    def create_many(self, rows: list[UsageGrantModel]) -> Awaitable[None]: ...
    def change(
        self, row: UsageGrantModel, changes: UsageGrantModel
    ) -> Awaitable[UsageGrantModel]: ...
    def change_many(
        self, rows: list[UsageGrantModel]
    ) -> Awaitable[list[UsageGrantModel]]: ...


class IUsageFactsReader(Protocol):
    def assignment(
        self, profile_id: int, node_id: int, lock: bool = False
    ) -> Awaitable[ProfileUsageAssignment | None]: ...
    def assignment_many(
        self, profile_ids: list[int], node_id: int, lock: bool = False
    ) -> Awaitable[list[ProfileUsageAssignment]]: ...
    def has_open_profile(
        self, profile_id: int, generation: int
    ) -> Awaitable[bool]: ...
    def has_open_profiles_many(
        self, keys: list[UsageProfileGenerationKey]
    ) -> Awaitable[list[UsageProfileGenerationKey]]: ...
    def reserved_bytes(
        self, subscription_id: int, generation: int, modes: list[str]
    ) -> Awaitable[int]: ...
    def reserved_bytes_many(
        self, keys: list[UsageGenerationKey], modes: list[str]
    ) -> Awaitable[list[UsageReservationTotal]]: ...


class IUsageEventService(Protocol):
    def create_many(self, rows: list[UsageEventModel]) -> Awaitable[None]: ...
    def by_identities_many(
        self, identities: list[UsageEventIdentity]
    ) -> Awaitable[list[UsageEventModel]]: ...


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
