from datetime import UTC, datetime

from pydantic import BaseModel, field_validator

from src.modules.network.ip_limits.domain.purchased import (
    EffectiveIpPolicyRead,
    PurchasedIpPolicyRead,
    SubscriptionIpPolicyRead,
)
from src.modules.sales.loyalty.domain.results import CustomerPriceQuote
from src.modules.sales.subscriptions.domain.models import SubscriptionModel


class SubscriptionOut(BaseModel):
    purchased_ip_policy: PurchasedIpPolicyRead | None = None
    effective_ip_policy: EffectiveIpPolicyRead | None = None
    commerce: CustomerPriceQuote | None = None
    entitlement_kind: str
    suspended_at: datetime | None
    suspension_clock: str | None
    suspension_reason: str | None
    suspended_by_reseller_account_id: int | None
    suspended_by_staff_id: int | None
    used_bytes: int
    provisioning_managed: bool
    activated_at: datetime | None
    group_id: int | None
    id: int
    customer_id: int
    plan_id: int
    quota_bytes: int | None
    price_rial: int
    duration_days: int | None
    expires_at: datetime | None
    status: str
    auto_renew: bool
    renewal_count: int
    failure_reason: str | None

    @field_validator("expires_at")
    @classmethod
    def utc_expiry(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return (
            value.replace(tzinfo=UTC)
            if value.tzinfo is None
            else value.astimezone(UTC)
        )

    @field_validator("activated_at", "suspended_at")
    @classmethod
    def utc_activation(cls, value: datetime | None) -> datetime | None:
        return (
            value.replace(tzinfo=UTC)
            if value is not None and value.tzinfo is None
            else value
        )

    @classmethod
    def from_model(
        cls,
        item: SubscriptionModel,
        ip_policy: SubscriptionIpPolicyRead | None = None,
    ) -> "SubscriptionOut":
        result = cls.model_validate(item, from_attributes=True)
        result.commerce = (
            CustomerPriceQuote.model_validate_json(item.commerce_json)
            if item.commerce_json is not None
            else None
        )
        if ip_policy is not None:
            result.purchased_ip_policy = ip_policy.purchased_ip_policy
            result.effective_ip_policy = ip_policy.effective_ip_policy
        return result


class SubscriptionControlOut(BaseModel):
    id: int
    subscription_id: int
    staff_id: int | None
    actor_account_id: int | None
    created_at: datetime
    action: str
    reason: str
    clock: str | None

    @field_validator("created_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value
