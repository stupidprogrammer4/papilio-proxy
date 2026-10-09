from enum import StrEnum
from string import Formatter
from typing import Literal

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field, model_validator

from src.modules.operations.notifications.domain.context import (
    SubscriptionNoticeContext,
)


class NotificationKind(StrEnum):
    CHECKOUT_ACTION_REQUIRED = "checkout_action_required"
    CHECKOUT_CANCELLED = "checkout_cancelled"
    CHECKOUT_EXPIRED = "checkout_expired"
    TIER_CHANGED = "tier_changed"
    DISCOUNT_APPLIED = "discount_applied"
    VOLUME_LOW = "volume_low"
    RENEWAL_AVAILABLE = "renewal_available"
    MANUAL = "manual"
    SUPPORT_REPLY = "support_reply"
    PAYMENT_APPROVED = "payment_approved"
    EXPIRY_SOON = "expiry_soon"
    RENEWAL_UNFUNDED = "renewal_unfunded"
    PROVISIONING_FAILED = "provisioning_failed"
    SUBSCRIPTION_ACTIVE = "subscription_active"


class NotificationChannelMode(StrEnum):
    INBOX = "inbox"
    TELEGRAM = "telegram"
    BOTH = "both"


class DeliveryStatus(StrEnum):
    SKIPPED = "skipped"
    PENDING = "pending"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    RETRY = "retry"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NotificationTemplate(BaseDTO):
    enabled: bool
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=16383)

    @model_validator(mode="after")
    def valid_template(self) -> "NotificationTemplate":
        for value in (self.title, self.body):
            for _, name, spec, conversion in Formatter().parse(value):
                if name is not None and (
                    name
                    not in {
                        "id",
                        "amount_toman",
                        "status",
                        "quota_gib",
                        "used_gib",
                        "remaining_gib",
                        "expires_at",
                        "renewal_price_toman",
                        "generation",
                        "threshold_code",
                    }
                    or spec
                    or conversion
                ):
                    raise ValueError(
                        "از شناسه، مبلغ تومان و وضعیت "
                        "بدون قالب اضافه استفاده کنید."
                    )
        return self


class NotificationPolicy(BaseDTO):
    enabled: bool
    channel_mode: NotificationChannelMode
    delivery_enabled: bool
    ambiguous_mode: Literal["hold", "retry"]
    backoff_mode: Literal["fixed", "exponential"]
    retry_seconds: int = Field(gt=0)
    max_retry_seconds: int = Field(gt=0)
    max_attempts: int = Field(gt=0)
    lease_seconds: int = Field(gt=0)
    max_message_chars: int = Field(gt=0, le=16383)
    templates: dict[NotificationKind, NotificationTemplate]

    @model_validator(mode="after")
    def complete(self) -> "NotificationPolicy":
        if not (
            set(NotificationKind)
            - {
                NotificationKind.CHECKOUT_ACTION_REQUIRED,
                NotificationKind.CHECKOUT_CANCELLED,
                NotificationKind.CHECKOUT_EXPIRED,
                NotificationKind.TIER_CHANGED,
                NotificationKind.DISCOUNT_APPLIED,
                NotificationKind.VOLUME_LOW,
                NotificationKind.RENEWAL_AVAILABLE,
            }
        ).issubset(self.templates):
            raise ValueError("سیاست هر نوع اعلان را مشخص کنید.")
        if (
            self.channel_mode != NotificationChannelMode.INBOX
            and self.max_message_chars > 4096
        ):
            raise ValueError(
                "متن تلگرام حداکثر ۴۰۹۶ کاراکتر دارد؛ "
                "برای متن بلند فقط صندوق را انتخاب کنید."
            )
        manual = self.templates[NotificationKind.MANUAL]
        if any(
            name is not None
            for value in (manual.title, manual.body)
            for _, name, _, _ in Formatter().parse(value)
        ):
            raise ValueError(
                "قالب پیام دستی متن ثابت دارد و متغیر رکورد ندارد."
            )
        examples = {
            "id": "9" * 19,
            "amount_toman": "9" * 20,
            "status": "و" * 64,
            "quota_gib": "9" * 24,
            "used_gib": "9" * 24,
            "remaining_gib": "9" * 24,
            "expires_at": "9" * 32,
            "renewal_price_toman": "9" * 20,
            "generation": "9" * 19,
            "threshold_code": "9" * 64,
        }
        for template in self.templates.values():
            title = template.title.format_map(examples)
            body = template.body.format_map(examples)
            if (
                len(title) > 160
                or len(body) > 16383
                or template.enabled
                and len(title + "\n" + body) > self.max_message_chars
            ):
                raise ValueError("قالب اعلان از سقف طول پیام بیشتر است.")
        if self.retry_seconds > self.max_retry_seconds:
            raise ValueError("فاصلهٔ اولیه از سقف تلاش بیشتر است.")
        return self


class NotificationEvent(BaseDTO):
    event_key: str = Field(min_length=8, max_length=160)
    kind: NotificationKind
    record_id: int = Field(gt=0, le=9223372036854775807)
    amount_rial: int | None = Field(default=None, ge=0, le=9223372036854775807)
    status: str = Field(default="", max_length=64)

    @model_validator(mode="after")
    def automatic(self) -> "NotificationEvent":
        if self.kind == NotificationKind.MANUAL:
            raise ValueError("Manual notices use their independent operation")
        return self


class ManualNotificationCreate(BaseDTO):
    request_key: str = Field(min_length=8, max_length=128)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    body: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def valid_override(self) -> "ManualNotificationCreate":
        if (self.title is None) != (self.body is None):
            raise ValueError(
                "عنوان و متن را با هم تعیین کنید "
                "یا از قالب پیش‌فرض استفاده کنید."
            )
        return self


class NotificationSearch(BaseQuery):
    q: str | None = Field(default=None, max_length=160)
    kind: NotificationKind | None = None
    is_read: bool | None = None
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class AdminNotificationSearch(NotificationSearch):
    status: DeliveryStatus | None = None
    customer_id: int | None = Field(default=None, gt=0)


class NotificationRead(BaseDTO):
    is_read: bool


class NotificationRecovery(BaseDTO):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=250)
    action: Literal["retry", "cancel"]


class SubscriptionNotificationEvent(NotificationEvent):
    context: SubscriptionNoticeContext

    @model_validator(mode="after")
    def matching_record(self) -> "SubscriptionNotificationEvent":
        if self.record_id != self.context.subscription_id or self.kind not in {
            NotificationKind.VOLUME_LOW,
            NotificationKind.EXPIRY_SOON,
            NotificationKind.RENEWAL_AVAILABLE,
        }:
            raise ValueError(
                "Subscription notice context must match its source"
            )
        expected_key = (
            f"subscription-alert:{self.record_id}:"
            f"{self.context.generation}:"
            f"{self.context.threshold_code}"
        )
        prefix = {
            NotificationKind.VOLUME_LOW: "quota:",
            NotificationKind.EXPIRY_SOON: "expiry:",
            NotificationKind.RENEWAL_AVAILABLE: "renewal",
        }[self.kind]
        if (
            self.event_key != expected_key
            or not self.context.threshold_code.startswith(prefix)
        ):
            raise ValueError(
                "Subscription event identity must match "
                "its rule and generation"
            )
        return self
