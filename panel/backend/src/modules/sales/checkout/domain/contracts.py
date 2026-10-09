from datetime import UTC, datetime
from typing import Literal

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import BaseModel, Field, field_validator, model_validator

from src.modules.billing.wallet.domain.results import (
    TopupPaymentInstructionRead,
)
from src.modules.network.ip_limits.domain.purchased import PlanIpPolicyRead

CheckoutState = Literal[
    "awaiting_funding",
    "ready",
    "action_required",
    "purchased",
    "cancelled",
    "expired",
]
FundingMode = Literal["wallet_only", "approved_topup"]

TransientConflictAction = Literal["retry_until_expiry", "require_confirmation"]


class PurchaseCheckoutPolicy(BaseDTO):
    transient_conflict_action: TransientConflictAction = "retry_until_expiry"
    enabled: bool = False
    admission_mode: Literal[
        "require_ready_bundle", "allow_manual_profiles"
    ] = "require_ready_bundle"
    default_expiry_seconds: int = Field(default=3600, gt=0)


class CheckoutCapacity(BaseModel):
    policy: PurchaseCheckoutPolicy = Field(
        default_factory=PurchaseCheckoutPolicy
    )
    scan_cron: str = Field(default="* * * * *", min_length=9)
    minimum_expiry_seconds: int = Field(default=60, gt=0)
    maximum_expiry_seconds: int = Field(default=86400, gt=0, le=31536000)
    max_offer_memberships: int = Field(default=256, gt=0)
    scan_limit: int = Field(default=100, gt=0)
    recheck_seconds: int = Field(default=30, gt=0)

    @model_validator(mode="after")
    def expiry_range(self) -> "CheckoutCapacity":
        if self.minimum_expiry_seconds > self.maximum_expiry_seconds:
            raise ValueError("Checkout expiry range is invalid")
        return self


class CheckoutCreate(BaseDTO):
    request_key: str = Field(min_length=8, max_length=64)
    plan_id: int = Field(gt=0)
    funding_mode: FundingMode
    expected_offer_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_price_rial: int = Field(ge=0)
    auto_renew: bool
    expiry_seconds: int = Field(gt=0)
    changed_offer_action: Literal["require_confirmation", "cancel"]
    topup_amount_rial: int | None = Field(default=None, gt=0)
    destination_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def funding_fields(self) -> "CheckoutCreate":
        if self.funding_mode == "approved_topup":
            if self.topup_amount_rial is None:
                raise ValueError("Approved-topup funding requires an amount")
        elif (
            self.topup_amount_rial is not None
            or self.destination_id is not None
        ):
            raise ValueError("Wallet funding cannot create a payment request")
        return self


class CheckoutReconfirm(BaseDTO):
    request_key: str = Field(min_length=8, max_length=64)
    expected_revision: int = Field(gt=0)
    expected_offer_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_price_rial: int = Field(ge=0)


class CheckoutCancel(BaseDTO):
    request_key: str = Field(min_length=8, max_length=64)
    expected_revision: int = Field(gt=0)


class CheckoutLookup(BaseDTO):
    request_key: str = Field(min_length=8, max_length=64)


class CheckoutSearch(BaseQuery):
    state: CheckoutState | None = None
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class CheckoutOffer(BaseModel):
    effective_ip_policy: PlanIpPolicyRead | None = None
    customer_id: int
    plan_id: int
    price_rial: int
    offer_sha256: str
    plan_title: str
    quota_bytes: int | None
    duration_days: int | None
    membership_count: int
    delivery_mode: Literal["configured_bundle", "manual_profiles"]
    default_expiry_seconds: int = Field(gt=0)
    captured_at: datetime


class CheckoutRead(BaseModel):
    id: int
    customer_id: int
    plan_id: int
    revision: int
    state: CheckoutState
    funding_mode: FundingMode
    delivery_mode: Literal["configured_bundle", "manual_profiles"]
    price_rial: int
    offer_sha256: str
    auto_renew: bool
    expires_at: datetime
    changed_offer_action: Literal["require_confirmation", "cancel"]
    topup_id: int | None
    subscription_id: int | None
    reason_code: str | None

    @field_validator("expires_at")
    @classmethod
    def expiry_utc(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class CheckoutPaymentInstructionRead(TopupPaymentInstructionRead):
    checkout_id: int = Field(gt=0)
