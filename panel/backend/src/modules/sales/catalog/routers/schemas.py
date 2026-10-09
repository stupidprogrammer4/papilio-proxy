from pydantic import BaseModel

from src.modules.network.ip_limits.domain.dtos import IpLimitChoice
from src.modules.network.ip_limits.domain.purchased import PlanIpPolicyRead
from src.modules.sales.catalog.domain.models import PlanModel
from src.modules.sales.catalog.domain.policies import (
    FulfillmentPolicy,
    QuotaPolicy,
)


class PlanOut(BaseModel):
    effective_ip_policy: PlanIpPolicyRead | None = None
    quota_policy: QuotaPolicy | None
    fulfillment: FulfillmentPolicy | None
    ip_limit: IpLimitChoice | None
    group_id: int | None
    id: int
    code: str
    title: str
    quota_bytes: int | None
    duration_days: int | None
    price_rial: int
    sort_order: int
    is_active: bool

    @classmethod
    def from_model(
        cls, plan: PlanModel, defaults: IpLimitChoice | None = None
    ) -> "PlanOut":
        values = plan.model_dump()
        values["quota_policy"] = (
            QuotaPolicy.model_validate_json(plan.quota_policy_json)
            if plan.quota_policy_json is not None
            else None
        )
        values["fulfillment"] = (
            FulfillmentPolicy.model_validate_json(plan.fulfillment_json)
            if plan.fulfillment_json is not None
            else None
        )
        values["ip_limit"] = (
            IpLimitChoice.model_validate_json(plan.ip_limit_json)
            if plan.ip_limit_json is not None
            else None
        )
        policy = values["ip_limit"] or defaults
        values["effective_ip_policy"] = (
            PlanIpPolicyRead(
                policy=policy,
                source="plan_override"
                if plan.ip_limit_json is not None
                else "current_defaults",
            )
            if policy is not None
            else None
        )
        return cls.model_validate(values)
