from __future__ import annotations

from hashlib import sha256
from html import escape
from pathlib import Path
from urllib.parse import quote, urlsplit

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    CopyTextButton,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.core.config import Settings
from bot.infra.qr import QrRenderer
from bot.models.checkout import CheckoutUnavailable
from bot.models.payments import PaymentProviderUnavailable
from bot.presentation.subscription_view import connection_links
from bot.services.access import AccessInactive, AccessService, AccessUnavailable
from bot.services.checkout import CheckoutService
from bot.services.payments import CallbackOutcome, PaymentSettlementError
from bot.services.subscriptions import (
    Plan,
    Protocol,
    Subscription,
    SubscriptionService,
    SubscriptionStatus,
    TelegramUser,
    UnknownPlanError,
)

RTL = "\u200f"
PAGE_SIZE = 6
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"
BANNER_PATH = ASSETS_DIR / "papilio-banner-v2.png"
LOGO_PATH = ASSETS_DIR / "papilio-logo-v2.png"
ANIMATION_PATH = ASSETS_DIR / "papilio-intro-v2.mp4"


def _key(code: str) -> str:
    """Keep administrator-defined plan codes inside Telegram's callback limit."""
    return sha256(code.encode("utf-8")).hexdigest()[:20]


def _home_text(name: str, sales_enabled: bool = False) -> str:
    return (
        f"{RTL}🦋 <b>به پاپیلیو خوش آمدی</b>\n"
        f"{RTL}سلام {escape(name[:64])} 👋\n"
        f"{RTL}اتصال تو، ساده و مرتب؛ از انتخاب پلن تا مدیریت مصرف، همین‌جا.\n\n"
        f"{RTL}📦 <b>پلن‌ها</b> — حجم، مدت و قیمت را مقایسه کن.\n"
        f"{RTL}📊 <b>سرویس‌های من</b> — لینک‌ها، مصرف، مانده و اعتبار.\n"
        f"{RTL}🔄 <b>ساب اختصاصی</b> — مسیرهای اتصال در یک لینک خصوصی.\n"
        f"{RTL}🧭 <b>راهنمای اتصال</b> — با مراحل استفاده از لینک آشنا شو.\n"
        f"{RTL}💬 <b>پشتیبانی</b> — اطلاعات لازم برای پیگیری مشکل را پیدا کن.\n\n"
        f"{RTL}👇 برای شروع، یکی از گزینه‌های زیر را انتخاب کن.\n"
        + (f"{RTL}💳 <i>پرداخت امن کارت‌به‌کارت با KPay؛ تحویل پس از تأیید پرداخت.</i>"
           if sales_enabled else f"{RTL}🧪 <i>پیش‌نمایش؛ خرید عمومی هنوز فعال نیست. سرویس فعال را از «سرویس‌های من» بگیر.</i>")
    )


async def _show_welcome(message: Message, name: str, sales_enabled: bool = False) -> None:
    if ANIMATION_PATH.is_file():
        await message.answer_animation(
            FSInputFile(ANIMATION_PATH),
            caption=_home_text(name, sales_enabled),
            reply_markup=_home_keyboard(),
        )
    elif BANNER_PATH.is_file():
        await message.answer_photo(
            FSInputFile(BANNER_PATH),
            caption=_home_text(name, sales_enabled),
            reply_markup=_home_keyboard(),
        )
    else:
        await message.answer(_home_text(name, sales_enabled), reply_markup=_home_keyboard())


def _toman(value: int) -> str:
    return f"{value:,}".replace(",", "٬") + " تومان"


def _size(value: int) -> str:
    if value < 1024**3:
        return f"{value / 1024**2:.0f} مگابایت"
    return f"{value / 1024**3:.1f}".rstrip("0").rstrip(".") + " گیگابایت"


def _plan_card(plan: Plan) -> str:
    return (
        f"{RTL}{escape(plan.emoji)} <b>{escape(plan.title)}</b>\n"
        f"{RTL}📶 {plan.traffic_gb} گیگابایت · 🗓 {plan.duration_days} روز\n"
        f"{RTL}💳 <b>{_toman(plan.price_toman)}</b>"
    )


def _subscription_card(record: Subscription, plan: Plan | None) -> str:
    state = {
        SubscriptionStatus.ACTIVE: "فعال",
        SubscriptionStatus.PAID_AWAITING_PROVISIONING: "پرداخت تأیید شد · در انتظار تحویل",
        SubscriptionStatus.TEST_AWAITING_PROVISIONING: "تست خصوصی · در انتظار تحویل",
        SubscriptionStatus.PENDING_PAYMENT: "ثبت اولیه · پرداخت تأیید نشده",
        SubscriptionStatus.EXPIRED: "منقضی‌شده",
        SubscriptionStatus.SUSPENDED: "متوقف‌شده",
    }[record.status]
    if record.status == SubscriptionStatus.PENDING_PAYMENT:
        return (
            f"{RTL}<b>{escape(plan.title) if plan else ('تست خصوصی' if record.price_rial == 0 else 'پلن آرشیوی')}</b> · {state}\n"
            f"{RTL}شناسهٔ پیگیری: <code>{escape(record.id[:8])}</code>\n"
            f"{RTL}مبلغ: {_toman(record.price_rial // 10)}"
        )
    if record.status in {
        SubscriptionStatus.PAID_AWAITING_PROVISIONING,
        SubscriptionStatus.TEST_AWAITING_PROVISIONING,
    }:
        payment_line = (
            f"{RTL}💳 مبلغ تأییدشده: {_toman(record.price_rial // 10)}\n"
            if record.price_rial else f"{RTL}🧪 بدون پرداخت · مخصوص تست\n"
        )
        return (
            f"{RTL}<b>{escape(plan.title) if plan else ('تست خصوصی' if record.price_rial == 0 else 'پلن آرشیوی')}</b> · {state}\n"
            f"{RTL}شناسهٔ پیگیری: <code>{escape(record.id[:8])}</code>\n"
            f"{payment_line}"
            f"{RTL}🔗 لینک اتصال هنوز صادر نشده است."
        )
    expiry = (
        record.expires_at.astimezone().strftime("%Y/%m/%d") if record.expires_at else "ثبت نشده"
    )
    return (
        f"{RTL}<b>{escape(plan.title) if plan else ('تست خصوصی' if record.price_rial == 0 else 'پلن آرشیوی')}</b> · {state}\n"
        f"{RTL}مصرف: {_size(record.traffic_used_bytes)} از {_size(record.traffic_limit_bytes)}\n"
        f"{RTL}مانده: {_size(record.traffic_remaining_bytes)} · انقضا: {expiry}"
    )


def _home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📦 مشاهدهٔ پلن‌ها", callback_data="plans", style="primary")],
            [
                InlineKeyboardButton(
                    text="📊 سرویس‌های من",
                    callback_data="subscriptions",
                    style="success",
                )
            ],
            [
                InlineKeyboardButton(text="🧭 راهنمای اتصال", callback_data="guide"),
                InlineKeyboardButton(text="💬 پشتیبانی", callback_data="support"),
            ],
            [InlineKeyboardButton(text="🦋 دربارهٔ پاپیلیو", callback_data="about")],
        ]
    )


def _section_keyboard(action: str, callback_data: str) -> InlineKeyboardMarkup:
    icon = {"plans": "📦", "subscriptions": "📊", "support": "💬"}.get(callback_data, "🔎")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{icon} {action}", callback_data=callback_data, style="primary"
                ),
                InlineKeyboardButton(text="🏠 خانه", callback_data="home"),
            ]
        ]
    )


def _short_title(title: str) -> str:
    return title if len(title) <= 16 else title[:15].rstrip() + "…"


def _plans_keyboard(plans: list[Plan], page: int = 0) -> InlineKeyboardMarkup:
    page = min(max(page, 0), max(0, (len(plans) - 1) // PAGE_SIZE))
    rows = [
        [
            InlineKeyboardButton(
                text=f"{plan.emoji} {_short_title(plan.title)} · {_toman(plan.price_toman)}",
                callback_data=f"plan:{_key(plan.code)}",
                style="primary",
            )
        ]
        for plan in plans[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    ]
    navigation: list[InlineKeyboardButton] = []
    if page:
        navigation.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"plans:{page - 1}"))
    if (page + 1) * PAGE_SIZE < len(plans):
        navigation.append(InlineKeyboardButton(text="بعدی ➡️", callback_data=f"plans:{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton(text="🏠 خانه", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _protocol_keyboard(plan_code: str) -> InlineKeyboardMarkup:
    key = _key(plan_code)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🛒 ثبت سفارش · هر دو لینک",
                callback_data=f"order:{key}:both",
                style="success",
            )],
            [InlineKeyboardButton(text="↩️ بازگشت به پلن‌ها", callback_data="plans")],
        ]
    )


def _order_keyboard(order_id: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if order_id:
        rows.append(
            [InlineKeyboardButton(text="📋 کپی کد پیگیری", copy_text=CopyTextButton(text=order_id))]
        )
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text="🔖 پیگیری درخواست",
                    callback_data="subscriptions",
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(text="📦 پلن‌ها", callback_data="plans"),
                InlineKeyboardButton(text="🏠 خانه", callback_data="home"),
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _subscription_url(settings: Settings, token: str, name: str = "🦋 Papilio") -> str:
    base = settings.subscription_public_base_url
    parsed = urlsplit(base or "")
    if (
        not base or parsed.scheme != "https" or not parsed.hostname
        or parsed.username or parsed.password or parsed.path not in {"", "/"}
    ):
        raise AccessUnavailable("Public subscription URL is not configured")
    return f"{base}/s/{token}#{quote(name[:40], safe='')}"


def _subscriptions_keyboard(records: list[Subscription]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"🔗 لینک‌های سرویس {record.id[:8]}",
            callback_data=f"access:{record.id}",
            style="success",
        )]
        for record in records[:8] if record.status == SubscriptionStatus.ACTIVE
    ]
    rows.extend([InlineKeyboardButton(text=f"💳 پرداخت سفارش {record.id[:8]}",
                                     callback_data=f"pay:{record.id}", style="primary")]
                for record in records[:8] if record.status == SubscriptionStatus.PENDING_PAYMENT)
    rows.append([InlineKeyboardButton(text="📦 پلن‌ها", callback_data="plans", style="primary")])
    rows.append([InlineKeyboardButton(text="🏠 خانه", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _access_keyboard(order_id: str, subscription_url: str, hysteria: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text="📋 کپی لینک اشتراک", copy_text=CopyTextButton(text=subscription_url.split('#')[0]),
            style="success",
        )],
        [InlineKeyboardButton(text="📊 مصرف و اعتبار", url=subscription_url.split('/s/')[0] + '/usage/' + subscription_url.split('/s/')[1].split('#')[0], style="primary"),
         InlineKeyboardButton(text="🖼 QR اشتراک", callback_data=f"accessqr:{order_id}")],
        [InlineKeyboardButton(text="⚡ VLESS", callback_data=f"link:vless:{order_id}"),
         InlineKeyboardButton(text="🌐 VMess", callback_data=f"link:vmess:{order_id}")],
        [InlineKeyboardButton(text="📊 سرویس‌های من", callback_data="subscriptions")],
    ]
    if hysteria:
        rows.insert(1, [InlineKeyboardButton(text="🚀 دریافت Hysteria2", callback_data=f"link:hysteria2:{order_id}", style="success")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _plans_text(plans: list[Plan], page: int, sales_enabled: bool = False) -> str:
    pages = max(1, (len(plans) + PAGE_SIZE - 1) // PAGE_SIZE)
    visible = plans[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    return (
        f"{RTL}📦 <b>پلن‌های پاپیلیو</b> · صفحهٔ {page + 1} از {pages}\n"
        f"{RTL}حجم و مدت مناسب خودت را انتخاب کن؛ قیمت هر بسته به تومان است.\n\n"
        + "\n\n".join(_plan_card(plan) for plan in visible)
        + f"\n\n{RTL}🔎 برای جزئیات و ثبت اولیه، دکمهٔ همان پلن را بزن.\n"
        + f"{RTL}ℹ️ مبنای حجم: هر گیگ برابر ۱۰۲۴ مگابایت.\n"
        + (f"{RTL}💳 <i>پرداخت با KPay · فعال‌سازی پس از تأیید واقعی پرداخت</i>" if sales_enabled
           else f"{RTL}🧪 <i>خرید عمومی هنوز فعال نیست؛ فعلاً مبلغی واریز نکن.</i>")
    )


def _guide_text(sales_enabled: bool = False) -> str:
    return (
        f"{RTL}🧭 <b>راهنمای اتصال، قدم‌به‌قدم</b>\n\n"
        f"{RTL}۱️⃣ پس از فعال‌سازی سرویس، لینک اشتراک اختصاصی را دریافت کن.\n"
        f"{RTL}۲️⃣ در برنامهٔ سازگار با پروتکل سرویس، افزودن اشتراک از لینک را انتخاب کن.\n"
        f"{RTL}۳️⃣ لینک را وارد و اشتراک را به‌روزرسانی کن؛ سپس یک اتصال را انتخاب کن.\n"
        f"{RTL}۴️⃣ اتصال را روشن کن و بازشدن یک وب‌سایت را بررسی کن.\n\n"
        f"{RTL}🔐 لینک اشتراک مثل رمز است؛ آن را در گروه یا برای دیگران نفرست.\n"
        f"{RTL}🔄 پس از تغییر تنظیمات سرویس، اشتراک را در برنامه به‌روزرسانی کن.\n"
        f"{RTL}💬 اگر وصل نشد، نام برنامه، سیستم‌عامل و متن خطا را آماده کن.\n\n"
        f"{RTL}🚀 <b>در Hiddify:</b> علامت + ← افزودن از کلیپ‌بورد ← به‌روزرسانی اشتراک.\n"
        f"{RTL}📊 حجم و اعتبار را در صفحهٔ مصرف ساب هم می‌بینی.\n"
        + ("" if sales_enabled else f"{RTL}🧪 <i>خرید عمومی هنوز فعال نیست؛ این راهنما برای سرویس فعال است.</i>")
    )


async def _show_view(
    callback: CallbackQuery,
    text: str,
    keyboard: InlineKeyboardMarkup,
    *,
    caption_ok: bool = False,
) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    if message.photo or message.animation:
        if caption_ok:
            await message.edit_caption(caption=text, reply_markup=keyboard)
        else:
            # Text views can exceed Telegram's media-caption limit.
            await message.edit_reply_markup(reply_markup=None)
            await message.answer(text, reply_markup=keyboard)
    else:
        await message.edit_text(text, reply_markup=keyboard)


async def _show_home(callback: CallbackQuery, sales_enabled: bool = False) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    name = callback.from_user.first_name
    if message.photo or message.animation:
        await _show_view(callback, _home_text(name, sales_enabled), _home_keyboard(), caption_ok=True)
    else:
        await message.edit_reply_markup(reply_markup=None)
        await _show_welcome(message, name, sales_enabled)


def build_router(
    service: SubscriptionService,
    settings: Settings,
    access_service: AccessService | None = None,
    checkout_service: CheckoutService | None = None,
) -> Router:
    router = Router(name="papilio")
    qr_renderer = QrRenderer()
    router.message.filter(F.chat.type == ChatType.PRIVATE)
    router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

    async def sales(telegram_id: int | None) -> bool:
        return await checkout_service.enabled(telegram_id) if checkout_service else False

    async def payment_view(callback: CallbackQuery, order_id: str) -> None:
        if checkout_service is None:
            await callback.answer("خرید عمومی هنوز باز نشده است.", show_alert=True)
            return
        try:
            checkout = await checkout_service.begin(callback.from_user.id, order_id)
        except CheckoutUnavailable as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        await callback.answer()
        await _show_view(callback,
            f"{RTL}💳 <b>پرداخت امن با KPay</b>\n\n"
            f"{RTL}مبلغ سفارش: <b>{_toman(checkout.amount_rial // 10)}</b>\n"
            f"{RTL}🔖 پیگیری: <code>{escape(order_id[:8])}</code>\n\n"
            f"{RTL}۱️⃣ درگاه را باز کن و دستور انتقال را دقیق دنبال کن.\n"
            f"{RTL}۲️⃣ بعد از انتقال، به همین صفحه برگرد و «بررسی پرداخت» را بزن.\n"
            f"{RTL}۳️⃣ پس از تأیید پرداخت، لینک خصوصی و QR خودکار ارسال می‌شود.\n\n"
            f"{RTL}🔐 تصویر رسید به‌تنهایی تأیید پرداخت نیست.",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 ورود به درگاه KPay", url=checkout.payment_url, style="success")],
                [InlineKeyboardButton(text="🔎 بررسی پرداخت", callback_data=f"paycheck:{order_id}", style="primary")],
                [InlineKeyboardButton(text="📊 سفارش‌های من", callback_data="subscriptions")],
            ]))

    async def selected_plan(key: str) -> Plan:
        for plan in await service.list_plans():
            if _key(plan.code) == key:
                return plan
        raise UnknownPlanError(key)

    async def subscription_text(telegram_id: int) -> str:
        records = await service.list_subscriptions(telegram_id)
        if not records:
            return (
                f"{RTL}📊 <b>سرویس‌های من</b>\n\n"
                f"{RTL}هنوز درخواست یا سرویسی نداری.\n"
                f"{RTL}📦 از بخش پلن‌ها، حجم و قیمت‌ها را مقایسه کن.\n"
                f"{RTL}🔖 پس از ثبت اولیه، وضعیت درخواستت همین‌جا دیده می‌شود."
            )
        plans_by_code = {plan.code: plan for plan in await service.list_plans(active_only=False)}
        body = f"{RTL}📊 <b>سرویس‌ها و درخواست‌های من</b>\n\n" + "\n\n".join(
            _subscription_card(item, plans_by_code.get(item.plan_code)) for item in records[:8]
        )
        if len(records) > 8:
            body += f"\n\n{RTL}۸ مورد تازه نمایش داده شد."
        if any(item.status == SubscriptionStatus.PENDING_PAYMENT for item in records[:8]):
            body += f"\n\n{RTL}<i>پرداخت‌نشده‌ها هنوز سرویس فعال ندارند.</i>"
        if any(item.status in {SubscriptionStatus.PAID_AWAITING_PROVISIONING, SubscriptionStatus.TEST_AWAITING_PROVISIONING} for item in records[:8]):
            body += f"\n\n{RTL}<i>دسترسی تأییدشده یا آزمایشی تا صدور لینک در صف فعال‌سازی می‌ماند.</i>"
        return body

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        sender = message.from_user
        if sender:
            await service.register_user(
                TelegramUser(sender.id, sender.full_name or "کاربر پاپیلیو", sender.username)
            )
        name = sender.first_name if sender else "دوست عزیز"
        await _show_welcome(message, name, await sales(sender.id if sender else None))

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        await message.answer(_guide_text(await sales(message.from_user.id if message.from_user else None)), reply_markup=_section_keyboard("پلن‌ها", "plans"))

    @router.message(Command("plans"))
    async def plans_command(message: Message) -> None:
        available_plans = await service.list_plans()
        if not available_plans:
            await message.answer(
                f"{RTL}<b>پلنی برای نمایش نیست.</b>\n{RTL}فهرست بعداً به‌روز می‌شود.",
                reply_markup=_section_keyboard("پشتیبانی", "support"),
            )
            return
        await message.answer(
            _plans_text(available_plans, 0, await sales(message.from_user.id if message.from_user else None)),
            reply_markup=_plans_keyboard(available_plans),
        )

    @router.message(Command("myservices", "subscriptions"))
    async def subscriptions_command(message: Message) -> None:
        if message.from_user:
            await message.answer(
                await subscription_text(message.from_user.id),
                reply_markup=_subscriptions_keyboard(
                    await service.list_subscriptions(message.from_user.id)
                ),
            )

    @router.callback_query(F.data == "home")
    async def home(callback: CallbackQuery) -> None:
        await callback.answer()
        await _show_home(callback, await sales(callback.from_user.id))

    @router.callback_query((F.data == "plans") | F.data.startswith("plans:"))
    async def plans(callback: CallbackQuery) -> None:
        data = callback.data or ""
        raw_page = data.removeprefix("plans:") if data.startswith("plans:") else "0"
        if not raw_page.isascii() or not raw_page.isdecimal():
            await callback.answer("درخواست معتبر نیست.", show_alert=True)
            return
        await callback.answer()
        available_plans = await service.list_plans()
        if not available_plans:
            await _show_view(
                callback,
                f"{RTL}<b>پلنی برای نمایش نیست.</b>\n{RTL}فهرست بعداً به‌روز می‌شود.",
                _section_keyboard("پشتیبانی", "support"),
            )
            return
        page = min(int(raw_page), (len(available_plans) - 1) // PAGE_SIZE)
        await _show_view(
            callback,
            _plans_text(available_plans, page, await sales(callback.from_user.id)),
            _plans_keyboard(available_plans, page),
        )

    @router.callback_query(F.data.startswith("plan:"))
    async def choose_protocol(callback: CallbackQuery) -> None:
        data = callback.data
        if data is None:
            await callback.answer("درخواست معتبر نیست.", show_alert=True)
            return
        key = data.split(":", 1)[1]
        try:
            plan = await selected_plan(key)
        except UnknownPlanError:
            await callback.answer("این پلن دیگر در دسترس نیست.", show_alert=True)
            return
        await callback.answer()
        await _show_view(
            callback,
            f"{RTL}{_plan_card(plan)}\n\n"
            f"{RTL}🔗 <b>یک اشتراک، مسیرهای متنوع اتصال</b>\n"
            f"{RTL}🚀 Hysteria2 · ⚡ VLESS · 🌐 VMess\n"
            f"{RTL}لینک ساب اختصاصی، QR و صفحهٔ مصرف؛ همه از یک حجم مشترک استفاده می‌کنند.\n\n"
            f"{RTL}🔖 با انتخاب زیر فقط درخواست و کد پیگیری ساخته می‌شود.\n"
            + (f"{RTL}💳 سپس وارد درگاه KPay می‌شوی؛ فعال‌سازی فقط پس از تأیید پرداخت است."
               if await sales(callback.from_user.id) else f"{RTL}🧪 <i>خرید عمومی هنوز باز نیست؛ فعلاً مبلغی واریز نکن.</i>"),
            _protocol_keyboard(plan.code),
        )

    @router.callback_query(F.data.startswith("order:"))
    async def create_order(callback: CallbackQuery) -> None:
        data = callback.data
        if data is None:
            await callback.answer("درخواست معتبر نیست.", show_alert=True)
            return
        parts = data.split(":")
        if len(parts) != 3 or len(parts[1]) != 20:
            await callback.answer("درخواست معتبر نیست.", show_alert=True)
            return
        try:
            plan = await selected_plan(parts[1])
            protocol = Protocol(parts[2])
            sender = callback.from_user
            await service.register_user(
                TelegramUser(sender.id, sender.full_name or "کاربر پاپیلیو", sender.username)
            )
            order = await service.create_order(callback.from_user.id, plan.code, protocol)
        except (UnknownPlanError, ValueError):
            await callback.answer("درخواست معتبر نیست.", show_alert=True)
            return
        if await sales(callback.from_user.id):
            await payment_view(callback, order.id)
            return
        await callback.answer("درخواست ثبت شد")
        await _show_view(
            callback,
            f"{RTL}✅ <b>درخواستت ثبت شد</b>\n\n"
            f"{RTL}{escape(plan.title)} · VLESS + VMess · {_toman(order.price_rial // 10)}\n"
            f"{RTL}🔖 کد پیگیری: <code>{escape(order.id[:8])}</code>\n\n"
            f"{RTL}📊 این درخواست در «سرویس‌های من» قابل مشاهده است.\n"
            f"{RTL}🧪 <i>پرداخت و فعال‌سازی انجام نشده است؛ فعلاً مبلغی واریز نکن.</i>",
            _order_keyboard(order.id),
        )

    @router.callback_query(F.data.startswith("pay:"))
    async def pay_order(callback: CallbackQuery) -> None:
        await payment_view(callback, (callback.data or "").removeprefix("pay:"))

    @router.callback_query(F.data.startswith("paycheck:"))
    async def check_payment(callback: CallbackQuery) -> None:
        if checkout_service is None:
            await callback.answer("بررسی پرداخت در دسترس نیست.", show_alert=True)
            return
        try:
            outcome = await checkout_service.check(callback.from_user.id, (callback.data or "").removeprefix("paycheck:"))
        except (CheckoutUnavailable, PaymentProviderUnavailable, PaymentSettlementError):
            await callback.answer("تأیید قطعی دریافت نشد؛ کمی بعد دوباره بررسی کن.", show_alert=True)
            return
        if outcome == CallbackOutcome.NOT_PAID:
            await callback.answer("پرداخت هنوز توسط KPay تأیید نشده است.", show_alert=True)
            return
        await callback.answer("پرداخت تأیید شد ✅")
        await _show_view(callback, f"{RTL}✅ <b>پرداخت تأیید شد</b>\n\n{RTL}سفارشت وارد صف فعال‌سازی شد. پس از صدور، لینک و QR خودکار همین‌جا ارسال می‌شوند.", _section_keyboard("سرویس‌های من", "subscriptions"))

    @router.callback_query(F.data == "subscriptions")
    async def subscriptions(callback: CallbackQuery) -> None:
        await callback.answer()
        await _show_view(
            callback,
            await subscription_text(callback.from_user.id),
            _subscriptions_keyboard(await service.list_subscriptions(callback.from_user.id)),
        )

    @router.callback_query(F.data.startswith("access:"))
    async def show_access(callback: CallbackQuery) -> None:
        order_id = (callback.data or "").removeprefix("access:")
        if access_service is None:
            await callback.answer("تحویل لینک هنوز فعال نیست.", show_alert=True)
            return
        try:
            access = await access_service.get_for_user(callback.from_user.id, order_id)
            if access is None:
                await callback.answer("سرویس فعالی با این شناسه پیدا نشد.", show_alert=True)
                return
            subscription_url = _subscription_url(settings, access.token, access.profile_name)
        except AccessInactive:
            await callback.answer("اعتبار سرویس یا حجم آن تمام شده است.", show_alert=True)
            return
        except AccessUnavailable:
            await callback.answer("مصرف سرویس تازه نیست؛ کمی بعد دوباره امتحان کن.", show_alert=True)
            return
        await callback.answer()
        text = (
            f"{RTL}🦋 <b>{escape(access.plan_title)}</b>\n"
            f"{RTL}✅ سرویس فعال · یک حجم مشترک برای همهٔ اتصال‌ها\n\n"
            f"{RTL}🔄 <b>اشتراک و مشاهدهٔ مصرف:</b>\n<code>{escape(subscription_url)}</code>\n\n"
            f"{RTL}📊 مصرف: {_size(access.traffic_used_bytes)} از {_size(access.traffic_limit_bytes)}"
            f" · مانده: {_size(access.traffic_remaining_bytes)}\n"
            f"{RTL}🗓 انقضا: {access.expires_at.astimezone().strftime('%Y/%m/%d')}\n\n"
            f"{RTL}🚀 کانفیگ‌های جداگانه را از دکمه‌ها بگیر یا ساب را یک‌بار وارد کن.\n"
            f"{RTL}🔐 این لینک‌ها خصوصی‌اند؛ در گروه منتشرشان نکن."
        )
        await _show_view(callback, text, _access_keyboard(order_id, subscription_url, bool(access.hysteria_link)))

    @router.callback_query(F.data.startswith("link:"))
    async def individual_link(callback: CallbackQuery) -> None:
        parts = (callback.data or "").split(":")
        if len(parts) != 3 or access_service is None:
            await callback.answer("درخواست معتبر نیست.", show_alert=True)
            return
        try:
            access = await access_service.get_for_user(callback.from_user.id, parts[2])
        except AccessUnavailable:
            await callback.answer("اطلاعات سرویس در دسترس نیست.", show_alert=True)
            return
        links = connection_links(access) if access else []
        link = next((value for value in links if value.startswith(parts[1]+"://")), None)
        if link is None:
            await callback.answer("این مسیر برای سرویس فعال نیست.", show_alert=True)
            return
        await callback.answer()
        if isinstance(callback.message, Message):
            await callback.message.answer(f"{RTL}🔗 <b>{escape(access.profile_name if access else '')}</b>\n\n<code>{escape(link)}</code>\n\n{RTL}🔐 فقط برای استفادهٔ شخصی؛ در گروه منتشر نکن.")

    @router.callback_query(F.data.startswith("accessqr:"))
    async def show_access_qr(callback: CallbackQuery) -> None:
        order_id = (callback.data or "").removeprefix("accessqr:")
        if access_service is None:
            await callback.answer("تحویل لینک هنوز فعال نیست.", show_alert=True)
            return
        try:
            access = await access_service.get_for_user(callback.from_user.id, order_id)
            if access is None:
                await callback.answer("سرویس فعالی با این شناسه پیدا نشد.", show_alert=True)
                return
            subscription_url = _subscription_url(settings, access.token, access.profile_name)
            image = await qr_renderer.render(subscription_url)
        except AccessInactive:
            await callback.answer("اعتبار سرویس یا حجم آن تمام شده است.", show_alert=True)
            return
        except (AccessUnavailable, ValueError):
            await callback.answer("QR فعلاً آماده نیست؛ کمی بعد دوباره امتحان کن.", show_alert=True)
            return
        await callback.answer()
        if isinstance(callback.message, Message):
            await callback.message.answer_photo(
                BufferedInputFile(image, filename="papilio-subscription.png"),
                caption=f"{RTL}🖼 QR اشتراک اختصاصی تو\n{RTL}🔐 فقط برای استفادهٔ شخصی نگهش دار.",
            )

    @router.callback_query(F.data == "guide")
    async def guide(callback: CallbackQuery) -> None:
        await callback.answer()
        await _show_view(callback, _guide_text(await sales(callback.from_user.id)), _section_keyboard("پلن‌ها", "plans"))

    @router.callback_query(F.data == "support")
    async def support(callback: CallbackQuery) -> None:
        await callback.answer()
        if settings.support_username:
            destination = f"@{escape(settings.support_username)}"
            text = (
                f"{RTL}💬 <b>پشتیبانی پاپیلیو</b>\n\n"
                f"{RTL}برای پیگیری با {destination} در ارتباط باش.\n\n"
                f"{RTL}🔖 کد درخواست · 📱 نام برنامه و سیستم‌عامل · 📝 متن خطا\n"
                f"{RTL}🔐 رمز، لینک اشتراک یا اطلاعات بانکی محرمانه را نفرست."
            )
        else:
            text = (
                f"{RTL}💬 <b>پشتیبانی پاپیلیو</b>\n\n"
                f"{RTL}راه ارتباطی هنوز تنظیم نشده است؛ این صفحه پیام را برای کسی نمی‌فرستد.\n\n"
                f"{RTL}🧭 مراحل اتصال را در «راهنمای اتصال» ببین.\n"
                f"{RTL}🔖 کد درخواستت در بخش «سرویس‌های من» است.\n"
                f"{RTL}🔐 لینک اشتراک و رمزها را در گروه‌های عمومی منتشر نکن."
            )
        await _show_view(callback, text, _section_keyboard("سرویس‌های من", "subscriptions"))

    @router.callback_query(F.data == "about")
    async def about(callback: CallbackQuery) -> None:
        await callback.answer()
        text = (
            f"{RTL}🦋 <b>پاپیلیو | Papilio</b>\n\n"
            f"{RTL}یک جای مشخص برای انتخاب پلن حجمی و پیگیری درخواست‌ها؛ داخل همین تلگرام.\n\n"
            f"{RTL}📦 مقایسهٔ حجم، مدت و قیمت پلن‌ها\n"
            f"{RTL}🔖 ثبت اولیه و مشاهدهٔ وضعیت درخواست\n"
            f"{RTL}📊 نمایش مصرف و انقضای ثبت‌شدهٔ سرویس\n"
            f"{RTL}🧭 راهنمای استفاده و نگهداری امن لینک\n\n"
            f"{RTL}💳 همهٔ قیمت‌ها به تومان نمایش داده می‌شوند.\n"
            + (f"{RTL}💳 <i>پرداخت KPay؛ تحویل فقط پس از تأیید واقعی تراکنش.</i>"
               if await sales(callback.from_user.id) else f"{RTL}🧪 <i>خرید عمومی هنوز باز نیست؛ سرویس‌های فعال قابل استفاده‌اند.</i>")
        )
        if isinstance(callback.message, Message) and LOGO_PATH.is_file():
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer_photo(
                FSInputFile(LOGO_PATH),
                caption=text,
                reply_markup=_section_keyboard("پلن‌ها", "plans"),
            )
            return
        await _show_view(callback, text, _section_keyboard("پلن‌ها", "plans"))

    return router
