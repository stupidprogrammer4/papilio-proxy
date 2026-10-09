from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from src.modules.network.ip_limits.domain.dtos import IpLimitChoice


class PurchasedIpPolicyRead(BaseModel):
    policy: IpLimitChoice
    source: Literal["plan_override", "purchase_defaults"]
    plan_id: int | None
    captured_at: datetime


class EffectiveIpPolicyRead(BaseModel):
    policy: IpLimitChoice | None
    source: Literal[
        "subscription_override", "purchased_snapshot", "legacy_unrestricted"
    ]
    scope: Literal["subscription"] = "subscription"
    enforcement: Literal["api_admission_only"] = "api_admission_only"
    core_enforcement_verified: Literal[False] = False
    transition: "IpPolicyTransitionRead | None" = None


class IpPolicyTransitionRead(BaseModel):
    status: Literal["draining", "blocked"]
    target_policy: IpLimitChoice
    mode: Literal["drain_leases", "require_closed_receipts"]
    retry_at: datetime | None
    reason: Literal[
        "ip_policy_draining",
        "legacy_lease_history_unknown",
        "closed_receipts_unavailable",
    ]


class IpTransitionModeRead(BaseModel):
    mode: Literal["drain_leases", "require_closed_receipts"]
    available: bool
    reason: Literal["closed_receipts_unavailable"] | None


class IpTransitionOptionsRead(BaseModel):
    default_mode: Literal["drain_leases", "require_closed_receipts"]
    choices: list[IpTransitionModeRead]


class SubscriptionIpPolicyRead(BaseModel):
    purchased_ip_policy: PurchasedIpPolicyRead | None
    effective_ip_policy: EffectiveIpPolicyRead


class PlanIpPolicyRead(BaseModel):
    policy: IpLimitChoice
    source: Literal["plan_override", "current_defaults"]
    scope: Literal["subscription"] = "subscription"
    enforcement: Literal["api_admission_only"] = "api_admission_only"
    core_enforcement_verified: Literal[False] = False


class IpLimitCapacityRead(BaseModel):
    max_ips_ceiling: int
    max_lease_seconds: int
    max_ban_seconds: int
