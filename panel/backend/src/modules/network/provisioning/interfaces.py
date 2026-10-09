from collections.abc import Awaitable
from typing import Literal, Protocol

from src.config.pagination import ServicePage
from src.modules.network.provisioning.domain.dtos import (
    ProvisionAcknowledgement,
    ProvisioningRetry,
    ProvisioningSearch,
)
from src.modules.network.provisioning.domain.models import (
    ProvisionRequestModel,
    ProvisionTaskModel,
)
from src.modules.network.provisioning.domain.results import NodeClaim
from src.modules.sales.catalog.domain.policies import FulfillmentPolicy


class IProvisioningCommand(Protocol):
    def resume(
        self, subscription_id: int, generation: int, reason: str, staff_id: int
    ) -> Awaitable[ProvisionRequestModel]: ...
    def retire(
        self,
        subscription_id: int,
        generation: int,
        completion: Literal["expire", "quota", "suspend", "cancel"],
        reason: str,
        staff_id: int | None,
    ) -> Awaitable[ProvisionRequestModel]: ...
    def queue(
        self, subscription_id: int, generation: int, policy: FulfillmentPolicy
    ) -> Awaitable[ProvisionRequestModel]: ...
    def prepare(
        self, id: int, manual: bool = False
    ) -> Awaitable[ProvisionRequestModel]: ...
    def cancel(
        self,
        subscription_id: int,
        generation: int,
        reason: str,
        staff_id: int | None,
    ) -> Awaitable[ProvisionRequestModel]: ...
    def retry(
        self, id: int, data: ProvisioningRetry
    ) -> Awaitable[ProvisionRequestModel]: ...
    def claim(
        self, code: str, key: str, task_id: int
    ) -> Awaitable[NodeClaim]: ...
    def acknowledge(
        self, code: str, key: str, task_id: int, data: ProvisionAcknowledgement
    ) -> Awaitable[ProvisionTaskModel]: ...


class IProvisioningQuery(Protocol):
    def due_ids(self) -> Awaitable[list[int]]: ...
    def requests(
        self, data: ProvisioningSearch
    ) -> Awaitable[ServicePage[ProvisionRequestModel]]: ...
    def tasks(
        self, request_id: int, data: ProvisioningSearch
    ) -> Awaitable[ServicePage[ProvisionTaskModel]]: ...
    def node_tasks(
        self, code: str, key: str, data: ProvisioningSearch
    ) -> Awaitable[ServicePage[ProvisionTaskModel]]: ...
