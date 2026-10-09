from dataclasses import dataclass

from src.modules.accounts.customers.domain.models import CustomerModel
from src.modules.operations.preferences.domain.dtos import IpDefaults
from src.modules.sales.catalog.domain.models import PlanModel
from src.modules.sales.catalog.domain.policies import (
    FulfillmentPolicy,
    QuotaPolicy,
)


@dataclass(frozen=True, slots=True)
class CheckoutMembershipFacts:
    configuration_id: int
    protocol: str
    is_selected: bool
    is_available: bool


@dataclass(frozen=True, slots=True)
class CheckoutOfferFacts:
    customer: CustomerModel
    plan: PlanModel
    memberships: list[CheckoutMembershipFacts]


@dataclass(frozen=True, slots=True)
class CheckoutFingerprintInput:
    """Detached scalar facts and effective policies for computation."""

    plan_id: int
    group_id: int | None
    quota_bytes: int | None
    duration_days: int | None
    price_rial: int
    fulfillment_json: str | None
    quota_policy_json: str | None
    ip_limit_json: str | None
    fulfillment_default: FulfillmentPolicy
    quota_default: QuotaPolicy
    ip_limit_default: IpDefaults
    configurations: tuple[tuple[int, str], ...]
