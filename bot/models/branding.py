from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BotBranding:
    name: str
    short_description: str
    description: str


DEFAULT_BRANDING = BotBranding(
    name="پاپیلیو | Papilio",
    short_description="🦋 پاپیلیو | 📦 پلن‌های حجمی · 📊 پیگیری سرویس · 🧭 راهنمای اتصال — نسخهٔ پیش‌نمایش",
    description=(
        "🦋 به پاپیلیو خوش آمدی!\n"
        "پنل شخصی سرویس تو، داخل همین تلگرام 👋\n\n"
        "📦 حجم، مدت و قیمت پلن‌ها را مقایسه کن.\n"
        "🔖 درخواستت را ثبت و وضعیت آن را پیگیری کن.\n"
        "📊 مصرف و انقضای ثبت‌شدهٔ سرویس را ببین.\n"
        "🧭 از راهنمای اتصال و بخش پشتیبانی کمک بگیر.\n\n"
        "💳 قیمت‌ها به تومان نمایش داده می‌شوند.\n"
        "🧪 نسخهٔ پیش‌نمایش: پرداخت و تحویل سرویس هنوز فعال نیست.\n"
        "👇 برای دیدن منو، «شروع» را بزن."
    ),
)


class BrandingValidationError(ValueError):
    """A profile field exceeds Telegram's limits or contains invalid text."""


def validate_branding(branding: BotBranding) -> None:
    fields = (
        ("نام", branding.name, 64),
        ("توضیح کوتاه", branding.short_description, 120),
        ("توضیح کامل", branding.description, 512),
    )
    for label, value, maximum in fields:
        if not value.strip() or len(value) > maximum or "\x00" in value:
            raise BrandingValidationError(f"{label} باید بین ۱ تا {maximum} نویسه باشد.")
