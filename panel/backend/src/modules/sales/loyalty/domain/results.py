from dataclasses import dataclass

from pydantic import BaseModel

from src.modules.sales.loyalty.domain.dtos import LoyaltyPolicy
from src.modules.sales.loyalty.domain.models import CustomerTierModel


@dataclass(frozen=True, slots=True)
class CustomerPurchaseVolumeFacts:
    net_bytes: int
    lifetime_bytes: int
    purchase_count: int
    lifetime_purchase_count: int
    legacy_purchase_count: int


class LoyaltyPolicyRead(BaseModel):
    revision: int
    values: LoyaltyPolicy


class CustomerTierRead(BaseModel):
    customer_id: int
    purchased_bytes: int
    purchase_count: int
    lifetime_purchase_count: int
    tier: CustomerTierModel | None
    next_tier: CustomerTierModel | None


class CustomerPriceQuote(BaseModel):
    customer_id: int
    plan_id: int
    base_price_rial: int
    price_rial: int
    discount_rial: int
    renewal_price_rial: int
    tier_code: str | None
    tier_discount_bps: int
    first_purchase_discount_bps: int
    policy_revision: int
