from datetime import UTC
from decimal import Decimal
from html import escape
from typing import Any

from aiogram.types import (
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from papilio_telegram.checkout import CheckoutPaymentInstruction
from papilio_telegram.commerce import (
    CustomerLoyalty,
    CustomerPriceQuote,
    CustomerRenewalEligibility,
    TrialAvailability,
    TrialSubscription,
)

_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(value: int | str) -> str:
    return str(value).translate(_DIGITS)


def toman(rial: int) -> str:
    whole, fraction = divmod(rial, 10)
    amount = f"{whole:,}" + (f"٫{fraction}" if fraction else "")
    return f"{fa(amount)} تومان"


def payment_instruction_text(value: CheckoutPaymentInstruction) -> str:
    labels = {
        "card": "شماره کارت",
        "iban": "شماره شبا",
        "bank_account": "شماره حساب",
    }
    lines = [
        "💳 <b>اطلاعات واریز</b>",
        "",
        escape(value.title),
        "🏦 بانک: " + escape(value.bank_name),
        "👤 به نام: " + escape(value.recipient),
        "",
        "📋 " + labels[value.kind] + ":",
        "<code>" + escape(value.account) + "</code>",
    ]
    if value.payable_amount_rial is not None:
        lines.extend(
            [
                "",
                "💰 <b>مبلغ قابل‌پرداخت (ریال)</b>",
                f"<code>{value.payable_amount_rial}</code>",
                "مبلغ دقیق واریز: "
                + fa(f"{value.payable_amount_rial:,}")
                + " ریال",
                "معادل: " + toman(value.payable_amount_rial),
            ]
        )
    if value.payment_identifier_mode == "rial_suffix4":
        lines.extend(
            [
                "",
                "🔎 شناسهٔ چهار رقم آخر مبلغ ریالی: "
                + fa(value.payment_identifier_code4 or ""),
                "⚠️ برای تطبیق خودکار، مبلغ بالا را دقیقاً "
                "به <b>ریال</b> وارد کنید؛ "
                "آن را گرد نکنید و چهار رقم آخر را تغییر ندهید.",
                "تأیید خودکار به دریافت و تطبیق پیامک واریز بستگی دارد؛ "
                "موارد مبهم بررسی می‌شوند.",
            ]
        )
    if value.instructions:
        lines.extend(["", "📝 " + escape(value.instructions)])
    lines.extend(
        [
            "",
            "📋 برای کپی، روی شماره یا مبلغ بزنید "
            "یا از دکمه‌های زیر استفاده کنید.",
            "✅ پس از تأیید، تمام مبلغ واریز به کیف پول شما می‌رود؛ "
            "اختلاف مبلغ کارمزد نیست.",
            "🧾 رسید و وضعیت پرداخت را از حساب کاربری پیگیری کنید.",
        ]
    )
    return "\n".join(lines)


def payment_instruction_menu(
    value: CheckoutPaymentInstruction,
    actions: InlineKeyboardMarkup,
) -> InlineKeyboardMarkup:
    labels = {
        "card": "کپی شماره کارت",
        "iban": "کپی شماره شبا",
        "bank_account": "کپی شماره حساب",
    }
    rows = [
        [
            InlineKeyboardButton(
                text="📋 " + labels[value.kind],
                copy_text=CopyTextButton(text=value.account),
            )
        ]
    ]
    if value.payable_amount_rial is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text="💰 کپی مبلغ ریالی",
                    copy_text=CopyTextButton(
                        text=str(value.payable_amount_rial)
                    ),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows + actions.inline_keyboard)


def menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧾 خریدهای من", callback_data="ch:1")],
            [
                InlineKeyboardButton(
                    text="🏅 گروه و امتیاز خرید من", callback_data="loyalty"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎁 اشتراک آزمایشی", callback_data="trial"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 حساب کاربری و رسیدها", callback_data="account"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🛍 خرید سرویس", callback_data="plans:1"
                ),
                InlineKeyboardButton(
                    text="📱 سرویس‌های من", callback_data="subs:1"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💳 کیف پول و شارژ", callback_data="wallet"
                ),
                InlineKeyboardButton(
                    text="💬 پشتیبانی", callback_data="support"
                ),
            ],
        ]
    )


def plan_menu(
    rows: list[dict[str, Any]], page: int, total_pages: int
) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=f"{row['title']} · {toman(int(row['price_rial']))}",
                callback_data=f"plan:{row['id']}",
            )
        ]
        for row in rows
    ]
    navigation = []
    if page > 1:
        navigation.append(
            InlineKeyboardButton(
                text="⬅️ صفحهٔ قبل", callback_data=f"plans:{page - 1}"
            )
        )
    if page < total_pages:
        navigation.append(
            InlineKeyboardButton(
                text="➡️ صفحهٔ بعد", callback_data=f"plans:{page + 1}"
            )
        )
    if navigation:
        buttons.append(navigation)
    buttons.append(
        [InlineKeyboardButton(text="↩️ بازگشت", callback_data="home")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def purchase_menu(plan_id: int, price_rial: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 خرید از کیف پول",
                    callback_data=f"buy:{plan_id}:0:{price_rial}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 خرید با تمدید خودکار",
                    callback_data=f"buy:{plan_id}:1:{price_rial}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🛍 بازگشت به پلن‌ها", callback_data="plans:1"
                )
            ],
        ]
    )


def wallet_menu(options_rial: list[int]) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=f"شارژ {toman(amount)}",
                callback_data=f"topup:{amount}",
            )
        ]
        for amount in options_rial
    ]
    buttons.append(
        [InlineKeyboardButton(text="↩️ بازگشت", callback_data="home")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def subscription_menu(
    rows: list[dict[str, Any]], page: int, total_pages: int
) -> InlineKeyboardMarkup:
    def button(row: dict[str, Any]) -> InlineKeyboardButton:
        enabled = bool(row["auto_renew"])
        state = "تمدید روشن" if enabled else "تمدید خاموش"
        return InlineKeyboardButton(
            text=f"اشتراک {fa(row['id'])} · {state}",
            callback_data=f"service:{row['id']}",
        )

    buttons = [[button(row)] for row in rows]
    navigation = []
    if page > 1:
        navigation.append(
            InlineKeyboardButton(
                text="⬅️ صفحهٔ قبل", callback_data=f"subs:{page - 1}"
            )
        )
    if page < total_pages:
        navigation.append(
            InlineKeyboardButton(
                text="➡️ صفحهٔ بعد", callback_data=f"subs:{page + 1}"
            )
        )
    if navigation:
        buttons.append(navigation)
    buttons.append(
        [InlineKeyboardButton(text="↩️ بازگشت", callback_data="home")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def service_menu(view: dict[str, Any]) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text="🔄 بررسی آمادگی تمدید",
                callback_data=f"renewal-status:{view['subscription_id']}",
            )
        ]
    ]
    if view.get("portal_url"):
        buttons.append(
            [
                InlineKeyboardButton(
                    text="📱 پنل و دریافت کانفیگ‌ها", url=view["portal_url"]
                )
            ]
        )
    if view.get("feed_url"):
        buttons.append(
            [InlineKeyboardButton(text="🔗 لینک اشتراک", url=view["feed_url"])]
        )
    if view["entitlement_kind"] != "trial":
        enabled = bool(view["auto_renew"])
        buttons.append(
            [
                InlineKeyboardButton(
                    text="خاموش‌کردن تمدید خودکار"
                    if enabled
                    else "فعال‌کردن تمدید خودکار",
                    callback_data=(
                        f"renew:{view['subscription_id']}:"
                        f"{0 if enabled else 1}"
                    ),
                )
            ]
        )
    if view.get("can_rotate_link"):
        buttons.append(
            [
                InlineKeyboardButton(
                    text="تغییر لینک خصوصی",
                    callback_data=f"rotate:{view['subscription_id']}",
                )
            ]
        )
    buttons.append(
        [InlineKeyboardButton(text="📱 سرویس‌های من", callback_data="subs:1")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def gibibytes(value: int) -> str:
    amount = Decimal(value) / Decimal(1024**3)
    return fa(format(amount, ".2f")) + " گیبی‌بایت"


def loyalty_text(value: CustomerLoyalty) -> str:
    lines = [
        "🏅 گروه و امتیاز خرید",
        "گروه فعلی: " + (value.tier.title if value.tier else "بدون گروه"),
        "اعتبار حجمی خریدهای واجد شرایط: " + gibibytes(value.purchased_bytes),
        "تعداد خریدهای واجد شرایط: " + fa(value.purchase_count),
    ]
    if value.next_tier is not None:
        lines.extend(
            [
                "گروه بعدی: " + value.next_tier.title,
                "حداقل اعتبار لازم: "
                + gibibytes(value.next_tier.minimum_bytes),
                "اعتبار باقی‌مانده تا گروه بعدی: "
                + gibibytes(
                    max(
                        value.next_tier.minimum_bytes - value.purchased_bytes,
                        0,
                    )
                ),
            ]
        )
    elif value.tier is not None:
        lines.append("در بالاترین گروه تعریف‌شده قرار دارید.")
    lines.append("تخفیف واقعی هر پلن هنگام بررسی قیمت نهایی نمایش داده می‌شود.")
    return "\n".join(lines)


def price_text(value: CustomerPriceQuote) -> str:
    lines = [
        "🏷 قیمت پایه: " + toman(value.base_price_rial),
        "🎁 تخفیف نهایی: " + toman(value.discount_rial),
        "💳 مبلغ پرداخت از کیف پول: " + toman(value.price_rial),
        "🔄 قیمت تمدید بر اساس قوانین فعلی: "
        + toman(value.renewal_price_rial),
    ]
    if value.tier_code is not None:
        lines.append("کد گروه: " + value.tier_code)
    if value.first_purchase_discount_bps:
        lines.append(
            "واجد شرایط تخفیف اولین خرید هستید؛ "
            "مبلغ نهایی شامل قوانین ترکیب و سقف تخفیف است."
        )
    return "\n".join(lines)


_TRIAL_REASONS = {
    "trial_disabled": "دریافت آزمایشی فعلاً غیرفعال است.",
    "trial_capacity": "شرایط آزمایشی فعلاً نیاز به بررسی مدیر دارد.",
    "trial_claim_limit": "به سقف تعداد دریافت‌های آزمایشی رسیده‌اید.",
    "trial_paid_customer": "این پیشنهاد مخصوص حساب‌های بدون خرید قبلی است.",
    "trial_active_exists": (
        "هنوز اشتراک آزمایشی فعال یا در حال آماده‌سازی دارید."
    ),
    "trial_cooldown": "فاصلهٔ لازم از دریافت آزمایشی قبلی هنوز تمام نشده است.",
    "customer_inactive": "دسترسی سرویس برای این حساب غیرفعال است.",
    "plan_inactive": "پلن آزمایشی فعلاً غیرفعال است.",
    "plan_group_disabled": "گروه تحویل پلن آزمایشی فعلاً غیرفعال است.",
    "trial_source_missing": "پلن آزمایشی فعلاً در دسترس نیست.",
}


def trial_text(offer: TrialAvailability) -> str:
    lines = [
        "🎁 اشتراک آزمایشی",
        "مدت: " + fa(offer.policy.duration_days) + " روز",
        "حجم: " + gibibytes(offer.policy.quota_bytes),
        "تعداد دریافت‌های ثبت‌شده: " + fa(offer.claims),
    ]
    if offer.eligible:
        lines.append("امکان ثبت درخواست دارید؛ تمدید خودکار ندارد.")
    else:
        lines.append(
            _TRIAL_REASONS.get(
                offer.reason or "", "دریافت با شرایط فعلی این حساب ممکن نیست."
            )
        )
    if offer.next_claim_at is not None:
        date = offer.next_claim_at.astimezone(UTC).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
        lines.append("زمان پایان فاصلهٔ دریافت: " + fa(date))
    return "\n".join(lines)


def trial_subscription_text(value: TrialSubscription) -> str:
    statuses = {
        "active": "فعال",
        "pending_provision": "منتظر آماده‌سازی",
        "failed": "آماده‌سازی ناموفق؛ نیاز به پیگیری",
        "cancelled": "لغوشده",
        "expired": "اعتبار پایان یافته",
        "exhausted": "حجم تمام شده",
        "suspended": "تعلیق‌شده",
        "customer_hold": "دسترسی سرویس متوقف است",
        "revoking": "در حال پایان سرویس",
    }
    return (
        "🎁 اشتراک آزمایشی "
        + fa(value.id)
        + "\nوضعیت فعلی: "
        + statuses.get(value.status, "نیاز به بررسی وضعیت سرویس")
        + "\nتمدید خودکار ندارد. جزئیات را از همین سرویس پیگیری کنید."
    )


def trial_service_menu(subscription_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📱 مشاهدهٔ همین سرویس",
                    callback_data=f"service:{subscription_id}",
                )
            ],
            [InlineKeyboardButton(text="↩️ بازگشت", callback_data="home")],
        ]
    )


def renewal_status_text(value: CustomerRenewalEligibility) -> str:
    reasons = {
        "trial_not_renewable": "اشتراک آزمایشی تمدید خودکار ندارد.",
        "subscription_not_renewable": "وضعیت فعلی سرویس امکان تمدید ندارد.",
        "customer_renewals_disabled": "دسترسی تمدید حساب غیرفعال است.",
        "payer_renewals_disabled": "دسترسی تمدید پرداخت‌کننده غیرفعال است.",
        "renewal_quote_unavailable": (
            "قیمت تمدید تحت قوانین فعلی در دسترس نیست."
        ),
    }
    lines = [
        f"🔄 آمادگی تمدید سرویس {fa(value.subscription_id)}",
        "تمدید طبق قوانین فعلی مجاز است."
        if value.eligible
        else reasons.get(value.reason_code or "", "تمدید فعلاً در دسترس نیست."),
        "قیمت فعلی تمدید: "
        + (
            toman(value.renewal_price_rial)
            if value.renewal_price_rial is not None
            else "در دسترس نیست"
        ),
    ]
    if value.payer_kind == "self":
        lines.append(
            "کیف پول من: "
            + (
                toman(value.wallet_balance_rial)
                if value.wallet_balance_rial is not None
                else "در دسترس نیست"
            )
        )
        if value.wallet_shortfall_rial is not None:
            lines.append("کسری کیف پول: " + toman(value.wallet_shortfall_rial))
    else:
        lines.append(
            "هزینهٔ سرویس با پرداخت‌کنندهٔ دیگری است؛ "
            "اطلاعات کیف پول او خصوصی است."
        )
    lines.append(
        "زمان یا شرط تمدید رسیده است."
        if value.renewal_due
        else "شرط تعیین‌شدهٔ تمدید هنوز نرسیده است."
    )
    lines.append(
        "تمدید خودکار مجاز است."
        if value.auto_renew_authorized
        else "تمدید خودکار مجاز نیست."
    )
    lines.append(
        "این بررسی به معنی انجام تمدید نیست؛ "
        "وضعیت سرویس را پس از اجرای خودکار بررسی کنید."
    )
    lines.append(
        "زمان بررسی: "
        + fa(value.checked_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC"))
    )
    return "\n".join(lines)
