from collections.abc import Awaitable
from datetime import datetime
from typing import Literal, Protocol

from src.config.pagination import ServicePage
from src.modules.network.ip_limits.domain.dtos import (
    IpAdmission,
    IpLimitChoice,
    IpManualBan,
    IpPolicyConfigureChoice,
    IpSessionSearch,
)
from src.modules.network.ip_limits.domain.models import (
    IpLimitPolicyModel,
    IpSessionModel,
    PurchasedIpPolicyModel,
)
from src.modules.network.ip_limits.domain.purchased import (
    SubscriptionIpPolicyRead,
)
from src.modules.network.ip_limits.domain.results import (
    IpAdmissionDecision,
    IpLimitDetail,
)


class IIpLimitPolicyCommand(Protocol):
    def configure(
        self, subscription_id: int, data: IpPolicyConfigureChoice
    ) -> Awaitable[IpLimitPolicyModel]: ...


class IIpAdmissionClock(Protocol):
    def now(self) -> Awaitable[datetime]: ...


class IIpLeaseTrackingService(Protocol):
    def initialize_purchase(self, subscription_id: int) -> Awaitable[None]: ...


class IPurchasedIpPolicyService(Protocol):
    def find(self, id: int) -> Awaitable[PurchasedIpPolicyModel | None]: ...
    def current(self, id: int) -> Awaitable[PurchasedIpPolicyModel | None]: ...
    def capture(
        self,
        subscription_id: int,
        plan_id: int | None,
        policy: IpLimitChoice,
        source: Literal["plan_override", "purchase_defaults"],
    ) -> Awaitable[PurchasedIpPolicyModel]: ...


class IIpPolicyProjectionQuery(Protocol):
    def single(self, id: int) -> Awaitable[SubscriptionIpPolicyRead]: ...
    def many(
        self, ids: list[int]
    ) -> Awaitable[dict[int, SubscriptionIpPolicyRead]]: ...


class IIpLimitQuery(Protocol):
    def detail(self, subscription_id: int) -> Awaitable[IpLimitDetail]: ...
    def sessions(
        self, subscription_id: int, data: IpSessionSearch
    ) -> Awaitable[ServicePage[IpSessionModel]]: ...


class IIpAdmissionCommand(Protocol):
    def admit(
        self, node_code: str, agent_key: str, data: IpAdmission
    ) -> Awaitable[IpAdmissionDecision]: ...


class IIpRestrictionCommand(Protocol):
    def ban(
        self,
        subscription_id: int,
        session_id: int,
        data: IpManualBan,
        staff_id: int,
    ) -> Awaitable[IpSessionModel]: ...
    def unban(
        self, subscription_id: int, session_id: int
    ) -> Awaitable[IpSessionModel]: ...
