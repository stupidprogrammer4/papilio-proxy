from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator


class BotMenuButton(BaseModel):
    action: Literal[
        "purchases",
        "loyalty",
        "trial",
        "account",
        "catalog",
        "subscriptions",
        "wallet",
        "support",
    ]
    label: str = Field(min_length=1, max_length=64)
    visible: bool


class BotPresentation(BaseModel):
    welcome_message: str = Field(
        default=(
            "سلام {display_name} 🌿\n"
            "به {brand_title} خوش آمدید.\n"
            "💰 موجودی کیف پول: {balance}"
        ),
        min_length=1,
        max_length=3000,
    )
    welcome_photo_url: str | None = None
    message_catalog: dict[str, str] = Field(default_factory=dict)
    menu_buttons: list[BotMenuButton] = Field(
        default_factory=lambda: [
            BotMenuButton(
                action="purchases", label="🧾 خریدهای من", visible=True
            ),
            BotMenuButton(
                action="loyalty",
                label="🏅 گروه و امتیاز خرید من",
                visible=True,
            ),
            BotMenuButton(
                action="trial", label="🎁 اشتراک آزمایشی", visible=True
            ),
            BotMenuButton(
                action="account", label="👤 حساب کاربری و رسیدها", visible=True
            ),
            BotMenuButton(
                action="catalog", label="🛍 خرید سرویس", visible=True
            ),
            BotMenuButton(
                action="subscriptions", label="📱 سرویس‌های من", visible=True
            ),
            BotMenuButton(
                action="wallet", label="💳 کیف پول و شارژ", visible=True
            ),
            BotMenuButton(action="support", label="💬 پشتیبانی", visible=True),
        ]
    )

    @field_validator("welcome_photo_url")
    @classmethod
    def https_photo_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("The bot photo must use HTTPS")
        return value

    @model_validator(mode="after")
    def all_menu_actions_are_unique(self) -> "BotPresentation":
        actions = [button.action for button in self.menu_buttons]
        if len(actions) != 8 or len(set(actions)) != 8:
            raise ValueError("The bot menu presentation is incomplete")
        return self


class CustomerTier(BaseModel):
    id: int
    code: str
    title: str
    minimum_bytes: int = Field(ge=0)
    discount_bps: int = Field(ge=0, le=10000)


class CustomerLoyalty(BaseModel):
    customer_id: int
    purchased_bytes: int = Field(ge=0)
    purchase_count: int = Field(ge=0)
    lifetime_purchase_count: int = Field(ge=0)
    tier: CustomerTier | None
    next_tier: CustomerTier | None


class CustomerPriceQuote(BaseModel):
    customer_id: int
    plan_id: int
    base_price_rial: int = Field(ge=0)
    price_rial: int = Field(ge=0)
    discount_rial: int = Field(ge=0)
    renewal_price_rial: int = Field(ge=0)
    tier_code: str | None
    tier_discount_bps: int = Field(ge=0, le=10000)
    first_purchase_discount_bps: int = Field(ge=0, le=10000)
    policy_revision: int = Field(ge=0)

    @model_validator(mode="after")
    def amount_contract(self) -> "CustomerPriceQuote":
        if self.base_price_rial - self.discount_rial != self.price_rial:
            raise ValueError("The quote amounts do not balance")
        return self


class TrialPolicy(BaseModel):
    enabled: bool
    plan_id: int | None
    eligibility: Literal["no_paid_purchase", "any_customer"]
    concurrent_mode: Literal["reject_active", "allow_multiple"]
    max_claims_per_customer: int = Field(gt=0)
    cooldown_seconds: int = Field(ge=0)
    quota_bytes: int = Field(gt=0, le=9223372036854775807)
    duration_days: int = Field(gt=0)


class TrialAvailability(BaseModel):
    policy: TrialPolicy
    capacity_valid: bool
    eligible: bool
    reason: str | None
    claims: int = Field(ge=0)
    next_claim_at: datetime | None

    @field_validator("next_claim_at")
    @classmethod
    def dated_cooldown(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("The trial cooldown must include its timezone")
        return value

    @model_validator(mode="after")
    def availability_contract(self) -> "TrialAvailability":
        if self.eligible and (
            not self.capacity_valid or not self.policy.enabled
        ):
            raise ValueError("The trial availability is inconsistent")
        return self


class TrialSubscription(BaseModel):
    id: int = Field(gt=0)
    customer_id: int = Field(gt=0)
    entitlement_kind: Literal["trial"]
    status: str
    auto_renew: Literal[False]


class CustomerRenewalEligibility(BaseModel):
    subscription_id: int = Field(gt=0)
    renewal_generation: int = Field(ge=0)
    checked_at: datetime
    auto_renew: bool
    quote_available: bool
    eligible: bool
    reason_code: str | None
    renewal_due: bool
    auto_renew_authorized: bool
    wallet_funded: bool | None
    payer_kind: Literal["self", "other", "none"]
    wallet_balance_rial: int | None = Field(default=None, ge=0)
    renewal_price_rial: int | None = Field(default=None, ge=0)
    wallet_shortfall_rial: int | None = Field(default=None, ge=0)

    @field_validator("checked_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Renewal observation must be timezone aware")
        return value

    @model_validator(mode="after")
    def private_payer(self) -> "CustomerRenewalEligibility":
        if self.payer_kind != "self" and any(
            value is not None
            for value in (
                self.wallet_balance_rial,
                self.wallet_shortfall_rial,
                self.wallet_funded,
            )
        ):
            raise ValueError("Another payer wallet must remain private")
        if self.eligible and not self.quote_available:
            raise ValueError("Eligible renewal needs a quote")
        return self


class SubscriptionNoticeAction(BaseModel):
    kind: Literal["subscription"]
    subscription_id: int = Field(gt=0)


class CheckoutNoticeAction(BaseModel):
    kind: Literal["checkout"]
    checkout_id: int = Field(gt=0)


class NotificationAuthorization(BaseModel):
    allowed: bool
    telegram_id: int | None
    text: str | None
    lease_until: datetime | None
    action: SubscriptionNoticeAction | CheckoutNoticeAction | None = None
