from dataclasses import dataclass
from datetime import datetime

from src.config.settings import IpLimitSettings
from src.modules.network.ip_limits.domain.models import IpLimitPolicyModel
from src.modules.network.ip_limits.domain.purchased import (
    EffectiveIpPolicyRead,
    IpTransitionOptionsRead,
    PurchasedIpPolicyRead,
)


@dataclass(frozen=True, slots=True)
class IpLimitDetail:
    subscription_id: int
    policy: IpLimitPolicyModel | None
    defaults: IpLimitSettings
    purchased_ip_policy: PurchasedIpPolicyRead | None
    effective_ip_policy: EffectiveIpPolicyRead
    transition_options: IpTransitionOptionsRead


@dataclass(frozen=True, slots=True)
class IpAdmissionDecision:
    subscription_id: int
    source_ip: str
    allowed: bool
    reason: str
    valid_until: datetime
    blocked_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class NodeSubscriptionAssignment:
    subscription_id: int
    node_id: int
    profile_count: int
    acknowledged_count: int


@dataclass(frozen=True, slots=True)
class IpAssignmentFacts:
    profile_id: int
    configuration_revision: int
    applied_generation: int | None
    applied_revision: int | None
