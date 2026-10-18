import ipaddress
from string import Formatter
from typing import Literal
from urllib.parse import urlsplit

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field, field_validator, model_validator

from src.modules.accounts.customers.domain.dtos import CustomerAccessState
from src.modules.accounts.resellers.domain.dtos import ResellerDefaults
from src.modules.billing.destinations.domain.dtos import CheckoutPolicy
from src.modules.billing.receipts.domain.dtos import ReceiptPolicy
from src.modules.network.qr_codes.domain.dtos import QrPolicy
from src.modules.operations.notifications.domain.dtos import NotificationPolicy
from src.modules.operations.preferences.domain.bot_messages import (
    BOT_MESSAGE_SOURCES,
)
from src.modules.sales.attention.domain.policies import SubscriptionAlertPolicy
from src.modules.sales.catalog.domain.policies import (
    FulfillmentPolicy,
    QuotaPolicy,
)
from src.modules.sales.checkout.domain.contracts import PurchaseCheckoutPolicy
from src.modules.sales.trials.domain.dtos import TrialPolicy
from src.modules.support.domain.dtos import SupportPolicy


class IpDefaults(BaseDTO):
    enabled: bool | None = None
    mode: Literal["reject_new", "replace_oldest"]
    max_ips: int = Field(gt=0)
    lease_seconds: int = Field(gt=0)
    ban_seconds: int = Field(gt=0)


BotLocale = Literal["fa", "en", "ru", "zh"]


class BotLocaleTextSettings(BaseDTO):
    welcome_message: str = Field(
        default=(
            "سلام {display_name} 🌿\n"
            "به {brand_title} خوش آمدید.\n"
            "💰 موجودی کیف پول: {balance}"
        ),
        min_length=1,
        max_length=3000,
    )
    purchases_button_label: str = Field(
        default="🧾 خریدهای من", min_length=1, max_length=64
    )
    loyalty_button_label: str = Field(
        default="🏅 گروه و امتیاز خرید من", min_length=1, max_length=64
    )
    trial_button_label: str = Field(
        default="🎁 اشتراک آزمایشی", min_length=1, max_length=64
    )
    account_button_label: str = Field(
        default="👤 حساب کاربری و رسیدها", min_length=1, max_length=64
    )
    catalog_button_label: str = Field(
        default="🛍 خرید سرویس", min_length=1, max_length=64
    )
    subscriptions_button_label: str = Field(
        default="📱 سرویس‌های من", min_length=1, max_length=64
    )
    wallet_button_label: str = Field(
        default="💳 کیف پول و شارژ", min_length=1, max_length=64
    )
    support_button_label: str = Field(
        default="💬 پشتیبانی", min_length=1, max_length=64
    )

    @field_validator("welcome_message")
    @classmethod
    def valid_welcome_template(cls, value: str) -> str:
        allowed = {"display_name", "brand_title", "balance"}
        try:
            parts = Formatter().parse(value)
            for _, field_name, format_spec, conversion in parts:
                if field_name is None:
                    continue
                if field_name not in allowed or format_spec or conversion:
                    raise ValueError("Unsupported bot welcome placeholder")
        except ValueError as exc:
            raise ValueError("Invalid bot welcome template") from exc
        return value


def default_bot_locale_texts() -> dict[BotLocale, BotLocaleTextSettings]:
    return {
        "fa": BotLocaleTextSettings(),
        "en": BotLocaleTextSettings(
            welcome_message=(
                "Hello {display_name} 🌿\n"
                "Welcome to {brand_title}.\n"
                "💰 Wallet balance: {balance}"
            ),
            purchases_button_label="🧾 My purchases",
            loyalty_button_label="🏅 Loyalty and purchase points",
            trial_button_label="🎁 Trial subscription",
            account_button_label="👤 Account and receipts",
            catalog_button_label="🛍 Buy a service",
            subscriptions_button_label="📱 My services",
            wallet_button_label="💳 Wallet and top-up",
            support_button_label="💬 Support",
        ),
        "ru": BotLocaleTextSettings(
            welcome_message=(
                "Здравствуйте, {display_name} 🌿\n"
                "Добро пожаловать в {brand_title}.\n"
                "💰 Баланс кошелька: {balance}"
            ),
            purchases_button_label="🧾 Мои покупки",
            loyalty_button_label="🏅 Уровень и баллы за покупки",
            trial_button_label="🎁 Пробная подписка",
            account_button_label="👤 Аккаунт и квитанции",
            catalog_button_label="🛍 Купить услугу",
            subscriptions_button_label="📱 Мои услуги",
            wallet_button_label="💳 Кошелёк и пополнение",
            support_button_label="💬 Поддержка",
        ),
        "zh": BotLocaleTextSettings(
            welcome_message=(
                "你好，{display_name} 🌿\n"
                "欢迎使用 {brand_title}。\n"
                "💰 钱包余额：{balance}"
            ),
            purchases_button_label="🧾 我的订单",
            loyalty_button_label="🏅 等级与购物积分",
            trial_button_label="🎁 试用订阅",
            account_button_label="👤 账户与收据",
            catalog_button_label="🛍 购买服务",
            subscriptions_button_label="📱 我的服务",
            wallet_button_label="💳 钱包与充值",
            support_button_label="💬 客服支持",
        ),
    }


def default_bot_message_catalog() -> dict[BotLocale, dict[str, str]]:
    return {
        "fa": {source: source for source in BOT_MESSAGE_SOURCES},
        "en": {source: "" for source in BOT_MESSAGE_SOURCES},
        "ru": {source: "" for source in BOT_MESSAGE_SOURCES},
        "zh": {source: "" for source in BOT_MESSAGE_SOURCES},
    }


class BotPresentationSettings(BaseDTO):
    catalog_version: Literal[2] = 2
    welcome_photo_url: str | None = Field(default=None, max_length=2048)
    show_purchases: bool = True
    show_loyalty: bool = True
    show_trials: bool = True
    show_account: bool = True
    show_catalog: bool = True
    show_subscriptions: bool = True
    show_wallet: bool = True
    show_support: bool = True
    localized_texts: dict[BotLocale, BotLocaleTextSettings] = Field(
        default_factory=default_bot_locale_texts
    )
    message_catalog: dict[BotLocale, dict[str, str]] = Field(
        default_factory=default_bot_message_catalog
    )

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_texts(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        payload = dict(value)
        if payload.get("catalog_version", 1) == 1:
            payload["catalog_version"] = 2
        catalog = default_bot_message_catalog()
        configured_catalog = payload.get("message_catalog") or {}
        unknown_locales = set(configured_catalog).difference(catalog)
        if unknown_locales:
            raise ValueError("Unknown bot message catalog locale")
        for locale, entries in configured_catalog.items():
            if not isinstance(entries, dict):
                continue
            unknown = set(entries).difference(BOT_MESSAGE_SOURCES)
            if unknown:
                raise ValueError("Unknown bot message catalog key")
            catalog[locale].update(entries)
        payload["message_catalog"] = catalog
        localized = payload.get("localized_texts")
        defaults = default_bot_locale_texts()
        if localized is None:
            legacy_fields = {
                "welcome_message",
                "purchases_button_label",
                "loyalty_button_label",
                "trial_button_label",
                "account_button_label",
                "catalog_button_label",
                "subscriptions_button_label",
                "wallet_button_label",
                "support_button_label",
            }
            legacy_values = {
                key: payload[key] for key in legacy_fields if key in payload
            }
            defaults["fa"] = BotLocaleTextSettings.model_validate(
                {**defaults["fa"].model_dump(), **legacy_values}
            )
            localized = {}
        merged = dict(defaults)
        merged.update(localized)
        payload["localized_texts"] = merged
        for key in (
            "welcome_message",
            "purchases_button_label",
            "loyalty_button_label",
            "trial_button_label",
            "account_button_label",
            "catalog_button_label",
            "subscriptions_button_label",
            "wallet_button_label",
            "support_button_label",
        ):
            payload.pop(key, None)
        return payload

    @field_validator("message_catalog")
    @classmethod
    def bounded_message_catalog(
        cls, value: dict[BotLocale, dict[str, str]]
    ) -> dict[BotLocale, dict[str, str]]:
        if set(value) != {"fa", "en", "ru", "zh"}:
            raise ValueError("Bot message catalog must include all locales")
        if any(
            len(message) > 4000
            for messages in value.values()
            for message in messages.values()
        ):
            raise ValueError("Bot message catalog entry is too long")
        return value

    @field_validator("welcome_photo_url")
    @classmethod
    def public_https_photo(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("Bot photo must use a public HTTPS URL")
        try:
            _ = parsed.port
        except ValueError:
            raise ValueError("Bot photo URL has an invalid port") from None
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("Bot photo cannot use a private IP address")
        return value


class BusinessPreferences(BaseDTO):
    purchase_checkout: PurchaseCheckoutPolicy | None = None
    subscription_alerts: SubscriptionAlertPolicy | None = None
    reseller_defaults: ResellerDefaults | None = None
    qr_codes: QrPolicy | None = None
    trials: TrialPolicy | None = None
    notifications: NotificationPolicy | None = None
    support: SupportPolicy | None = None
    customer_creation_access: CustomerAccessState | None = None
    receipts: ReceiptPolicy | None = None
    checkout: CheckoutPolicy | None = None
    quota_policy: QuotaPolicy | None = None
    customer_link_rotation: bool | None = None
    fulfillment: FulfillmentPolicy | None = None
    bot_presentation: BotPresentationSettings = Field(
        default_factory=BotPresentationSettings
    )
    brand_title: str = Field(min_length=2, max_length=100)
    payment_instructions: str | None = Field(default=None, max_length=4000)
    support_handle: str | None = Field(
        default=None, max_length=100, pattern=r"^@?[A-Za-z0-9_]+$"
    )
    topup_options_rial: list[int] = Field(min_length=1)
    max_plan_duration_days: int = Field(gt=0)
    payment_stale_hours: int = Field(gt=0)
    node_health_stale_seconds: int = Field(gt=0)
    subscription_expiry_warning_hours: int = Field(gt=0)
    provisioning_attention_minutes: int = Field(gt=0)
    ip_defaults: IpDefaults

    @field_validator("topup_options_rial")
    @classmethod
    def valid_amounts(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values) or len(set(values)) != len(
            values
        ):
            raise ValueError(
                "Topup options must be distinct positive rial amounts"
            )
        return values


class PreferencesWrite(BaseDTO):
    expected_revision: int = Field(ge=0)
    values: BusinessPreferences


class PreferencesSearch(BaseQuery):
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)
