from pydantic import BaseModel

from src.modules.network.ip_limits.domain.dtos import IpLimitChoice
from src.modules.network.ip_limits.domain.purchased import IpLimitCapacityRead
from src.modules.sales.catalog.domain.policies import (
    FulfillmentPolicy,
    QuotaPolicy,
)


class PlanPolicyDefaults(BaseModel):
    ip_limit_capacity: IpLimitCapacityRead
    quota_policy: QuotaPolicy
    fulfillment: FulfillmentPolicy
    ip_limit: IpLimitChoice
