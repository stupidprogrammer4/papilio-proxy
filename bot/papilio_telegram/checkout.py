"""Typed API checkout contracts and bounded, ephemeral interaction drafts."""

from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime
from secrets import token_hex
from time import monotonic
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

FundingMode = Literal["wallet_only", "approved_topup"]
CheckoutState = Literal[
    "awaiting_funding",
    "ready",
    "action_required",
    "purchased",
    "cancelled",
    "expired",
]


class CheckoutOffer(BaseModel):
    customer_id: int = Field(gt=0)
    plan_id: int = Field(gt=0)
    price_rial: int = Field(ge=0)
    offer_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_title: str
    quota_bytes: int | None = Field(ge=0)
    duration_days: int | None = Field(gt=0)
    membership_count: int = Field(ge=0)
    delivery_mode: Literal["configured_bundle", "manual_profiles"]
    default_expiry_seconds: int = Field(gt=0)
    captured_at: datetime

    @field_validator("captured_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Checkout offer must be dated in UTC")
        return value


class CheckoutRead(BaseModel):
    id: int = Field(gt=0)
    customer_id: int = Field(gt=0)
    plan_id: int = Field(gt=0)
    revision: int = Field(gt=0)
    state: CheckoutState
    funding_mode: FundingMode
    delivery_mode: Literal["configured_bundle", "manual_profiles"]
    price_rial: int = Field(ge=0)
    offer_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    auto_renew: bool
    expires_at: datetime
    changed_offer_action: Literal["require_confirmation", "cancel"]
    topup_id: int | None
    subscription_id: int | None
    reason_code: str | None

    @field_validator("expires_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Checkout expiry must include its timezone")
        return value


class CheckoutRetirement(BaseModel):
    request_key: str = Field(min_length=8, max_length=64)
    status: Literal["retired", "purchased"]
    intent: CheckoutRead | None

    @model_validator(mode="after")
    def outcome(self) -> "CheckoutRetirement":
        if self.status == "purchased" and (
            self.intent is None
            or self.intent.subscription_id is None
            or self.intent.state != "purchased"
        ):
            raise ValueError("Purchased retirement requires original service")
        if (
            self.status == "retired"
            and self.intent is not None
            and (
                self.intent.subscription_id is not None
                or self.intent.state not in {"cancelled", "expired"}
            )
        ):
            raise ValueError("Retired attempt cannot remain purchaseable")
        return self


class CheckoutFundingPolicy(BaseModel):
    destination_mode: Literal["required", "optional", "legacy"]
    allowed_methods: list[Literal["card", "iban", "bank_account"]]
    minimum_topup_rial: int = Field(gt=0)
    maximum_topup_rial: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_range(self) -> "CheckoutFundingPolicy":
        if self.minimum_topup_rial > self.maximum_topup_rial:
            raise ValueError("Invalid funding range")
        return self


class CheckoutDestination(BaseModel):
    destination_id: int = Field(gt=0)
    title: str
    kind: Literal["card", "iban", "bank_account"]
    account: str
    recipient: str
    bank_name: str
    instructions: str | None


class CheckoutPaymentInstruction(CheckoutDestination):
    topup_id: int | None = Field(default=None, gt=0)
    requested_amount_rial: int | None = Field(default=None, gt=0)
    payable_amount_rial: int | None = Field(default=None, gt=0)
    payment_identifier_mode: (
        Literal["exact_requested", "rial_suffix4"] | None
    ) = None
    payment_identifier_code4: str | None = Field(
        default=None, pattern=r"^[0-9]{4}$"
    )

    @model_validator(mode="after")
    def captured_amount(self) -> "CheckoutPaymentInstruction":
        if self.payment_identifier_mode is None:
            if any(
                value is not None
                for value in (
                    self.topup_id,
                    self.requested_amount_rial,
                    self.payable_amount_rial,
                    self.payment_identifier_code4,
                )
            ):
                raise ValueError("Incomplete captured payment amount")
            return self
        if (
            self.topup_id is None
            or self.requested_amount_rial is None
            or self.payable_amount_rial is None
            or self.payable_amount_rial < self.requested_amount_rial
        ):
            raise ValueError("Invalid captured payment amount")
        if self.payment_identifier_mode == "rial_suffix4":
            expected_code = f"{self.payable_amount_rial % 10000:04d}"
            if self.payment_identifier_code4 != expected_code:
                raise ValueError("Payment identifier mismatches rial amount")
        elif self.payment_identifier_code4 is not None:
            raise ValueError("Exact payment cannot have an amount identifier")
        return self


class CheckoutCreate(BaseModel):
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


class CheckoutReconfirm(BaseModel):
    request_key: str = Field(min_length=8, max_length=64)
    expected_revision: int = Field(gt=0)
    expected_offer_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_price_rial: int = Field(ge=0)


class CheckoutCancel(BaseModel):
    request_key: str = Field(min_length=8, max_length=64)
    expected_revision: int = Field(gt=0)


@dataclass(frozen=True, slots=True)
class CheckoutDraftLimits:
    max_entries: int
    lifetime_seconds: int
    history_page_size: int

    def __post_init__(self) -> None:
        if (
            min(
                self.max_entries, self.lifetime_seconds, self.history_page_size
            )
            <= 0
        ):
            raise ValueError("Checkout capacities must be positive")


@dataclass(frozen=True, slots=True)
class CheckoutDraft:
    telegram_id: int
    offer: CheckoutOffer
    expires_at: float
    checkout_id: int | None = None
    expected_revision: int | None = None
    attempted_create: CheckoutCreate | None = None
    funding_amount_rial: int | None = None
    funding_destination_id: int | None = None
    funding_destination_required: bool = False
    retirement_started: bool = False
    retirement_result: CheckoutRetirement | None = None


class CheckoutDrafts:
    """Missing drafts require API lookup or explicit review."""

    def __init__(self, limits: CheckoutDraftLimits) -> None:
        self.limits = limits
        self.rows: OrderedDict[str, CheckoutDraft] = OrderedDict()

    def put(
        self,
        telegram_id: int,
        offer: CheckoutOffer,
        intent: CheckoutRead | None = None,
    ) -> str:
        nonce = token_hex(8)
        self.rows[nonce] = CheckoutDraft(
            telegram_id,
            offer,
            monotonic() + self.limits.lifetime_seconds,
            intent.id if intent else None,
            intent.revision if intent else None,
        )
        while len(self.rows) > self.limits.max_entries:
            self.rows.popitem(last=False)
        return nonce

    def get(self, telegram_id: int, nonce: str) -> CheckoutDraft | None:
        draft = self.rows.get(nonce)
        if draft is None or draft.telegram_id != telegram_id:
            return None
        if draft.expires_at <= monotonic():
            self.rows.pop(nonce, None)
            return None
        return draft

    def remember_create(self, nonce: str, body: CheckoutCreate) -> None:
        draft = self.rows[nonce]
        if draft.attempted_create is None:
            self.rows[nonce] = replace(draft, attempted_create=body)

    def select_funding(
        self,
        nonce: str,
        amount_rial: int,
        destination_id: int | None,
        destination_required: bool = False,
    ) -> bool:
        draft = self.rows.get(nonce)
        if (
            draft is None
            or draft.expires_at <= monotonic()
            or draft.attempted_create is not None
            or draft.retirement_started
        ):
            return False
        self.rows[nonce] = replace(
            draft,
            funding_amount_rial=amount_rial,
            funding_destination_id=destination_id,
            funding_destination_required=destination_required,
        )
        return True

    def begin_retirement(self, telegram_id: int, nonce: str) -> None:
        draft = self.rows.get(nonce)
        if draft is not None and draft.telegram_id == telegram_id:
            self.rows[nonce] = replace(draft, retirement_started=True)

    def finish_retirement(
        self, telegram_id: int, nonce: str, result: CheckoutRetirement
    ) -> None:
        draft = self.rows.get(nonce)
        if draft is not None and draft.telegram_id == telegram_id:
            self.rows[nonce] = replace(
                draft,
                retirement_started=True,
                retirement_result=result,
            )
