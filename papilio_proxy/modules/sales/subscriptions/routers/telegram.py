from __future__ import annotations

import asyncio
import io
from hashlib import sha256
from html import escape
from pathlib import Path
from urllib.parse import quote, urlsplit

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    CopyTextButton,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from papilio_proxy.config.settings import Settings
from papilio_proxy.modules.accounts.users.domain.entities import UserBlockedError
from papilio_proxy.modules.network.subscriptions.app.services import (
    AccessInactive,
    AccessService,
    AccessUnavailable,
)
from papilio_proxy.modules.network.subscriptions.infra.qr import QrRenderer
from papilio_proxy.modules.network.subscriptions.routers.cards import expiry_label
from papilio_proxy.modules.network.subscriptions.routers.views import connection_links
from papilio_proxy.modules.sales.payments.app.services import PaymentService
from papilio_proxy.modules.sales.payments.domain.entities import (
    PaymentError,
    PaymentInstructions,
    ReceiptStatus,
)
from papilio_proxy.modules.sales.payments.infra.images import MAX_RECEIPT_BYTES
from papilio_proxy.modules.sales.subscriptions.app.services import (
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
ASSETS_DIR = Path(__file__).resolve().parents[5] / "assets"
BANNER_PATH = ASSETS_DIR / "papilio-banner-v2.png"
LOGO_PATH = ASSETS_DIR / "papilio-logo-v2.png"
ANIMATION_PATH = ASSETS_DIR / "papilio-intro-v2.mp4"


class ReceiptUpload(StatesGroup):
    image = State()


def _key(code: str) -> str:
    """Keep administrator-defined plan codes inside Telegram's callback limit."""
    return sha256(code.encode("utf-8")).hexdigest()[:20]


def _home_text(name: str, sales_enabled: bool = False) -> str:
    return (
        f"{RTL}🦋 <b>به پاپیلیو خوش آمدی</b>\n"
        f"{RTL}سلام {escape(name[:64])} 👋\n"
        f"{RTL}پلنت را انتخاب کن؛ بعد از پرداخت، اشتراکت را همین‌جا بگیر.\n\n"
        f"{RTL}📦 <b>خرید اشتراک</b> · حجم و مدت مناسب تو\n"
        f"{RTL}📊 <b>سرویس‌های من</b> · لینک اتصال، حجم باقی‌مانده و اعتبار\n"
        f"{RTL}🧭 راهنمای اتصال و 💬 پشتیبانی، همیشه در دسترس\n\n"
        f"{RTL}👇 از دکمه‌های زیر شروع کن.\n"
        + (
            f"{RTL}💳 <i>پرداخت کارت‌به‌کارت · ارسال عکس رسید</i>"
            if sales_enabled
            else f"{RTL}🧪 <i>پیش‌نمایش؛ خرید عمومی هنوز فعال نیست. سرویس فعال را از «سرویس‌های من» بگیر.</i>"
        )
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
            if record.price_rial
            else f"{RTL}🧪 بدون پرداخت · مخصوص تست\n"
        )
        return (
            f"{RTL}<b>{escape(plan.title) if plan else ('تست خصوصی' if record.price_rial == 0 else 'پلن آرشیوی')}</b> · {state}\n"
            f"{RTL}شناسهٔ پیگیری: <code>{escape(record.id[:8])}</code>\n"
            f"{payment_line}"
            f"{RTL}🔗 لینک اتصال هنوز صادر نشده است."
        )
    expiry = expiry_label(record.expires_at) if record.expires_at else "ثبت نشده"
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
            [InlineKeyboardButton(text="🧾 پیگیری خرید", callback_data="orders")],
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
            [
                InlineKeyboardButton(
                    text="💳 ادامهٔ خرید",
                    callback_data=f"order:{key}:both",
                    style="success",
                )
            ],
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
                    text="🧾 پیگیری خرید",
                    callback_data="orders",
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
        not base
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
    ):
        raise AccessUnavailable("Public subscription URL is not configured")
    return f"{base}/s/{token}#{quote(name[:40], safe='')}"


def _subscriptions_keyboard(records: list[Subscription]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"🔗 لینک‌های سرویس {record.id[:8]}",
                callback_data=f"access:{record.id}",
                style="success",
            )
        ]
        for record in records[:8]
        if record.status == SubscriptionStatus.ACTIVE
    ]
    rows.append([InlineKeyboardButton(text="📦 پلن‌ها", callback_data="plans", style="primary")])
    rows.append([InlineKeyboardButton(text="🏠 خانه", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _access_keyboard(
    order_id: str, subscription_url: str, hysteria: bool = False
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="📋 کپی لینک اشتراک",
                copy_text=CopyTextButton(text=subscription_url),
                style="success",
            )
        ],
        [
            InlineKeyboardButton(
                text="📊 مصرف و اعتبار",
                url=subscription_url.split("/s/")[0]
                + "/usage/"
                + subscription_url.split("/s/")[1].split("#")[0],
                style="primary",
            ),
            InlineKeyboardButton(text="🖼 QR اشتراک", callback_data=f"accessqr:{order_id}"),
        ],
        [
            InlineKeyboardButton(text="⚡ لینک اتصال", callback_data=f"link:vless:{order_id}"),
            InlineKeyboardButton(text="🔗 لینک جایگزین", callback_data=f"link:vmess:{order_id}"),
        ],
        [InlineKeyboardButton(text="📊 سرویس‌های من", callback_data="subscriptions")],
    ]
    if hysteria:
        rows.insert(
            1,
            [
                InlineKeyboardButton(
                    text="🚀 اتصال پیشنهادی",
                    callback_data=f"link:hysteria2:{order_id}",
                    style="success",
                )
            ],
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _payment_card(instructions: PaymentInstructions) -> str:
    card = " ".join(instructions.card_number[i : i + 4] for i in range(0, 16, 4))
    return (
        f"{RTL}💳 <b>{escape(instructions.method_title)}</b>\n\n"
        f"{RTL}📦 {escape(instructions.plan_title)}\n"
        f"{RTL}مبلغ: <b>{_toman(instructions.amount_rial // 10)}</b>\n\n"
        f"{RTL}🏦 بانک: {escape(instructions.bank_name)}\n"
        f"{RTL}👤 به نام: {escape(instructions.account_holder)}\n"
        f"<code>{escape(card)}</code>\n\n"
        f"{RTL}پس از واریز، دکمهٔ «ارسال رسید» را بزن و عکس رسیدت را بفرست.\n"
        f"{RTL}اشتراکت پس از تأیید پرداخت، در همین چت تحویل داده می‌شود."
    )


def _payment_keyboard(instructions: PaymentInstructions) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 کپی شماره کارت",
                    copy_text=CopyTextButton(text=instructions.card_number),
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📸 ارسال رسید",
                    callback_data=f"receipt:{instructions.order_id}",
                    style="success",
                )
            ],
            [
                InlineKeyboardButton(text="🧾 پیگیری خرید", callback_data="orders"),
                InlineKeyboardButton(text="🏠 خانه", callback_data="home"),
            ],
        ]
    )


def _plans_text(plans: list[Plan], page: int, sales_enabled: bool = False) -> str:
    pages = max(1, (len(plans) + PAGE_SIZE - 1) // PAGE_SIZE)
    visible = plans[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    return (
        f"{RTL}📦 <b>پلن‌های پاپیلیو</b> · صفحهٔ {page + 1} از {pages}\n"
        f"{RTL}حجم و مدت مناسب خودت را انتخاب کن؛ قیمت هر بسته به تومان است.\n\n"
        + "\n\n".join(_plan_card(plan) for plan in visible)
        + f"\n\n{RTL}👇 برای خرید، پلن دلخواهت را انتخاب کن.\n"
        + (
            f"{RTL}💳 <i>پرداخت کارت‌به‌کارت</i>"
            if sales_enabled
            else f"{RTL}🧪 <i>خرید عمومی هنوز فعال نیست؛ فعلاً مبلغی واریز نکن.</i>"
        )
    )


def _guide_text(sales_enabled: bool = False) -> str:
    return (
        f"{RTL}🧭 <b>راهنمای اتصال، قدم‌به‌قدم</b>\n\n"
        f"{RTL}۱️⃣ پس از فعال‌سازی سرویس، لینک اشتراک اختصاصی را دریافت کن.\n"
        f"{RTL}۲️⃣ در برنامهٔ اتصال، گزینهٔ «افزودن اشتراک از لینک» را انتخاب کن.\n"
        f"{RTL}۳️⃣ لینک را وارد و اشتراک را به‌روزرسانی کن؛ سپس یک اتصال را انتخاب کن.\n"
        f"{RTL}۴️⃣ اتصال را روشن کن و بازشدن یک وب‌سایت را بررسی کن.\n\n"
        f"{RTL}🔐 لینک اشتراک مثل رمز است؛ آن را در گروه یا برای دیگران نفرست.\n"
        f"{RTL}🔄 پس از تغییر تنظیمات سرویس، اشتراک را در برنامه به‌روزرسانی کن.\n"
        f"{RTL}💬 اگر وصل نشد، نام برنامه، سیستم‌عامل و متن خطا را آماده کن.\n\n"
        f"{RTL}🚀 <b>در Hiddify:</b> علامت + ← افزودن از کلیپ‌بورد ← به‌روزرسانی اشتراک.\n"
        f"{RTL}📊 حجم و اعتبار را در صفحهٔ مصرف ساب هم می‌بینی.\n"
        + (
            ""
            if sales_enabled
            else f"{RTL}🧪 <i>خرید عمومی هنوز فعال نیست؛ این راهنما برای سرویس فعال است.</i>"
        )
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
    try:
        if message.photo or message.animation:
            if caption_ok:
                await message.edit_caption(caption=text, reply_markup=keyboard)
            else:
                # Text views can exceed Telegram's media-caption limit.
                await message.edit_reply_markup(reply_markup=None)
                await message.answer(text, reply_markup=keyboard)
        else:
            await message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest as exc:
        if "message is not modified" not in exc.message.lower():
            raise


async def _show_home(callback: CallbackQuery, sales_enabled: bool = False) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    name = callback.from_user.first_name
    if message.photo or message.animation:
        await _show_view(
            callback, _home_text(name, sales_enabled), _home_keyboard(), caption_ok=True
        )
    else:
        await message.edit_reply_markup(reply_markup=None)
        await _show_welcome(message, name, sales_enabled)


def build_router(
    service: SubscriptionService,
    settings: Settings,
    access_service: AccessService | None = None,
    payment_service: PaymentService | None = None,
) -> Router:
    router = Router(name="papilio")
    qr_renderer = QrRenderer()
    receipt_slots = asyncio.Semaphore(2)
    router.message.filter(F.chat.type == ChatType.PRIVATE)
    router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

    async def sales(telegram_id: int | None) -> bool:
        return await payment_service.enabled(telegram_id) if payment_service else False

    async def payment_view(callback: CallbackQuery, order_id: str) -> None:
        if payment_service is None:
            await callback.answer("خرید عمومی هنوز باز نشده است.", show_alert=True)
            return
        await callback.answer()
        try:
            instructions = await payment_service.instructions(callback.from_user.id, order_id)
        except (PaymentError, UserBlockedError) as exc:
            await _show_view(
                callback,
                f"💳 <b>پرداخت آماده نشد</b>\n\n{escape(str(exc))}",
                _order_keyboard(order_id),
            )
            return
        await show_instructions(callback, instructions)

    async def show_instructions(callback: CallbackQuery, instructions: PaymentInstructions) -> None:
        assert payment_service is not None
        order_id = instructions.order_id
        if await payment_service.status(callback.from_user.id, order_id) == ReceiptStatus.PENDING:
            await _show_view(
                callback,
                "⏳ <b>رسیدت در حال بررسی است.</b>\n\nنتیجه در همین چت به تو اطلاع داده می‌شود؛ نیازی به واریز دوباره نیست.",
                _order_keyboard(order_id),
            )
            return
        await _show_view(
            callback,
            _payment_card(instructions),
            _payment_keyboard(instructions),
        )

    async def selected_plan(key: str) -> Plan:
        for plan in await service.list_plans():
            if _key(plan.code) == key:
                return plan
        raise UnknownPlanError(key)

    async def subscription_text(telegram_id: int) -> str:
        records = await service.list_services(telegram_id)
        if not records:
            return (
                f"{RTL}📊 <b>سرویس‌های من</b>\n\n"
                f"{RTL}هنوز اشتراک فعالی نداری.\n"
                f"{RTL}📦 پلنت را انتخاب کن؛ پس از فعال‌سازی، سرویست اینجا نمایش داده می‌شود."
            )
        plans_by_code = {plan.code: plan for plan in await service.list_plans(active_only=False)}
        body = f"{RTL}📊 <b>سرویس‌های من</b>\n\n" + "\n\n".join(
            _subscription_card(item, plans_by_code.get(item.plan_code)) for item in records[:8]
        )
        if len(records) > 8:
            body += f"\n\n{RTL}۸ مورد تازه نمایش داده شد."
        return body

    async def order_view(telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
        records = await service.list_orders(telegram_id)
        plans_by_code = {plan.code: plan for plan in await service.list_plans(active_only=False)}
        text = f"{RTL}🧾 <b>پیگیری خرید</b>\n\n"
        text += (
            "\n\n".join(
                _subscription_card(item, plans_by_code.get(item.plan_code)) for item in records[:8]
            )
            if records
            else "خریدی در انتظار پرداخت یا تحویل نداری."
        )
        rows = [
            [
                InlineKeyboardButton(
                    text=f"🔎 وضعیت پرداخت {record.id[:8]}",
                    callback_data=f"paycheck:{record.id}",
                    style="primary",
                )
            ]
            for record in records[:8]
            if record.status == SubscriptionStatus.PENDING_PAYMENT
        ]
        rows.append(
            [
                InlineKeyboardButton(
                    text="📊 سرویس‌های من", callback_data="subscriptions", style="success"
                ),
                InlineKeyboardButton(text="🏠 خانه", callback_data="home"),
            ]
        )
        return text, InlineKeyboardMarkup(inline_keyboard=rows)

    async def payment_result(telegram_id: int, order_id: str) -> tuple[str, InlineKeyboardMarkup]:
        records = await service.list_subscriptions(telegram_id)
        owned = next((item for item in records if item.id == order_id), None)
        if owned is None:
            return "🔐 این سفارش برای حساب تو پیدا نشد.", _home_keyboard()
        outcome = None
        if owned.status == SubscriptionStatus.PENDING_PAYMENT and payment_service:
            outcome = await payment_service.status(telegram_id, order_id)
        if owned.status == SubscriptionStatus.ACTIVE:
            if access_service:
                try:
                    access = await access_service.get_for_user(telegram_id, order_id)
                    if access:
                        url = _subscription_url(settings, access.token, access.profile_name)
                        return (
                            (
                                f"✅ <b>پرداخت موفق بود؛ سرویست آماده است!</b>\n\n{escape(access.plan_title)}\n"
                                "👇 لینک اتصال و وضعیت مصرف را از دکمه‌های زیر بگیر."
                            ),
                            _access_keyboard(order_id, url, bool(access.hysteria_link)),
                        )
                except AccessUnavailable:
                    pass
            return (
                "✅ <b>پرداخت موفق بود.</b>\n\nسرویست فعال است؛ لینک آن در «سرویس‌های من» قرار دارد.",
                _section_keyboard("سرویس‌های من", "subscriptions"),
            )
        if owned.status == SubscriptionStatus.PAID_AWAITING_PROVISIONING:
            return (
                "✅ <b>پرداخت موفق بود.</b>\n\nاشتراکت در حال آماده‌سازی است؛ لینک و QR همین‌جا ارسال می‌شوند. نیازی به پرداخت دوباره نیست.",
                _section_keyboard("پیگیری خرید", "orders"),
            )
        if owned.status in {SubscriptionStatus.EXPIRED, SubscriptionStatus.SUSPENDED}:
            return (
                "✅ <b>پرداخت این خرید قبلاً تأیید شده است.</b>\n\nوضعیت فعلی سرویس را در «سرویس‌های من» ببین.",
                _section_keyboard("سرویس‌های من", "subscriptions"),
            )
        if outcome == ReceiptStatus.REJECTED:
            return (
                "❌ <b>رسیدت تأیید نشد.</b>\n\nاگر رسید اشتباهی فرستاده‌ای، عکس درست را ارسال کن. برای پیگیری پرداخت با پشتیبانی در ارتباط باش.",
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="📸 ارسال رسید جدید",
                                callback_data=f"receipt:{order_id}",
                                style="primary",
                            )
                        ],
                        [InlineKeyboardButton(text="💬 پشتیبانی", callback_data="support")],
                    ]
                ),
            )
        if outcome is None:
            return (
                "💳 <b>منتظر دریافت رسید هستیم.</b>\n\nپس از واریز، عکس رسید این خرید را بفرست.",
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="💳 اطلاعات پرداخت",
                                callback_data=f"pay:{order_id}",
                                style="primary",
                            )
                        ],
                        [InlineKeyboardButton(text="🏠 خانه", callback_data="home")],
                    ]
                ),
            )
        return (
            "⏳ <b>رسیدت در حال بررسی است.</b>\n\nنتیجه در همین چت به تو اطلاع داده می‌شود؛ نیازی به واریز دوباره نیست.",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔎 بررسی دوباره",
                            callback_data=f"paycheck:{order_id}",
                            style="primary",
                        )
                    ],
                    [
                        InlineKeyboardButton(text="🧾 پیگیری خرید", callback_data="orders"),
                        InlineKeyboardButton(text="🏠 خانه", callback_data="home"),
                    ],
                ]
            ),
        )

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        sender = message.from_user
        if sender:
            await service.register_user(
                TelegramUser(sender.id, sender.full_name or "کاربر پاپیلیو", sender.username)
            )
            argument = (message.text or "").partition(" ")[2].strip()
            if argument.startswith("paid_"):
                order_id = argument.removeprefix("paid_")
                text, keyboard = await payment_result(sender.id, order_id)
                await message.answer(text, reply_markup=keyboard)
                return
        name = sender.first_name if sender else "دوست عزیز"
        await _show_welcome(message, name, await sales(sender.id if sender else None))

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        await message.answer(
            _guide_text(await sales(message.from_user.id if message.from_user else None)),
            reply_markup=_section_keyboard("پلن‌ها", "plans"),
        )

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
            _plans_text(
                available_plans, 0, await sales(message.from_user.id if message.from_user else None)
            ),
            reply_markup=_plans_keyboard(available_plans),
        )

    @router.message(Command("myservices", "subscriptions"))
    async def subscriptions_command(message: Message) -> None:
        if message.from_user:
            await message.answer(
                await subscription_text(message.from_user.id),
                reply_markup=_subscriptions_keyboard(
                    await service.list_services(message.from_user.id)
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
    async def choose_plan(callback: CallbackQuery) -> None:
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
        enabled = await sales(callback.from_user.id)
        await _show_view(
            callback,
            f"{RTL}{_plan_card(plan)}\n\n"
            f"{RTL}✨ همراه با لینک اشتراک، QR اتصال و نمایش حجم باقی‌مانده\n\n"
            + (
                f"{RTL}💳 کارت‌به‌کارت کن و عکس رسیدت را بفرست؛ اشتراکت پس از تأیید همین‌جا تحویل داده می‌شود."
                if enabled
                else f"{RTL}خرید عمومی هنوز فعال نیست."
            ),
            _protocol_keyboard(plan.code) if enabled else _section_keyboard("پلن‌ها", "plans"),
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
        if not await sales(callback.from_user.id):
            await callback.answer("خرید عمومی هنوز فعال نیست.", show_alert=True)
            return
        try:
            plan = await selected_plan(parts[1])
            Protocol(parts[2])  # Accept old buttons without exposing transport choices.
            sender = callback.from_user
            await service.register_user(
                TelegramUser(sender.id, sender.full_name or "کاربر پاپیلیو", sender.username)
            )
        except UserBlockedError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        except (UnknownPlanError, ValueError):
            await callback.answer("درخواست معتبر نیست.", show_alert=True)
            return
        assert payment_service is not None
        methods = await payment_service.methods(enabled_only=True)
        if len(methods) != 1:
            await callback.answer()
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=f"💳 {method.title}",
                            callback_data=f"purchase:{_key(plan.code)}:{_key(method.id)}",
                            style="primary",
                        )
                    ]
                    for method in methods
                ]
                + [[InlineKeyboardButton(text="🏠 خانه", callback_data="home")]]
            )
            await _show_view(callback, "💳 <b>روش پرداخت را انتخاب کن</b>", keyboard)
            return
        await callback.answer()
        try:
            instructions = await payment_service.begin(
                callback.from_user.id, plan.code, methods[0].id
            )
        except (PaymentError, UserBlockedError) as exc:
            await _show_view(callback, escape(str(exc)), _section_keyboard("پلن‌ها", "plans"))
            return
        await show_instructions(callback, instructions)

    @router.callback_query(F.data.startswith("purchase:"))
    async def choose_payment_method(callback: CallbackQuery) -> None:
        parts = (callback.data or "").split(":")
        if len(parts) != 3 or payment_service is None:
            await callback.answer("درخواست معتبر نیست.", show_alert=True)
            return
        try:
            plan = await selected_plan(parts[1])
            method = next(
                (
                    item
                    for item in await payment_service.methods(enabled_only=True)
                    if _key(item.id) == parts[2]
                ),
                None,
            )
            if method is None:
                raise PaymentError("این روش پرداخت در دسترس نیست.")
            await service.register_user(
                TelegramUser(
                    callback.from_user.id, callback.from_user.full_name, callback.from_user.username
                )
            )
            instructions = await payment_service.begin(callback.from_user.id, plan.code, method.id)
        except (PaymentError, UserBlockedError, UnknownPlanError) as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        await callback.answer()
        await show_instructions(callback, instructions)

    @router.callback_query(F.data.startswith("receipt:"))
    async def request_receipt(callback: CallbackQuery, state: FSMContext) -> None:
        order_id = (callback.data or "").removeprefix("receipt:")
        if payment_service is None:
            await callback.answer("ارسال رسید در دسترس نیست.", show_alert=True)
            return
        try:
            await payment_service.instructions(callback.from_user.id, order_id)
            if (
                await payment_service.status(callback.from_user.id, order_id)
                == ReceiptStatus.PENDING
            ):
                raise PaymentError("رسیدت در حال بررسی است؛ منتظر نتیجه بمان.")
        except (PaymentError, UserBlockedError) as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        await state.set_state(ReceiptUpload.image)
        await state.update_data(order_id=order_id)
        await callback.answer()
        await _show_view(
            callback,
            "📸 <b>عکس رسید پرداخت را بفرست</b>\n\nمبلغ، تاریخ و شمارهٔ پیگیری روی عکس خوانا باشند.",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ انصراف", callback_data="receipt_cancel")],
                ]
            ),
        )

    @router.callback_query(F.data == "receipt_cancel")
    async def cancel_receipt(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await callback.answer()
        await _show_home(callback, await sales(callback.from_user.id))

    @router.message(ReceiptUpload.image, F.photo | F.document)
    async def receive_receipt(message: Message, state: FSMContext) -> None:
        if message.from_user is None or message.bot is None or payment_service is None:
            return
        data = await state.get_data()
        order_id = data.get("order_id")
        if not isinstance(order_id, str):
            await state.clear()
            await message.answer("از بخش «پیگیری خرید»، دکمهٔ ارسال رسید خریدت را بزن.")
            return
        file = message.photo[-1] if message.photo else message.document
        if file is None:
            return
        if file.file_size and file.file_size > MAX_RECEIPT_BYTES:
            await message.answer("عکس رسید باید حداکثر ۵ مگابایت باشد.")
            return
        try:
            async with receipt_slots:
                buffer = io.BytesIO()
                await message.bot.download(file.file_id, destination=buffer)
                await payment_service.submit_receipt(
                    message.from_user.id, order_id, buffer.getvalue()
                )
        except (PaymentError, UserBlockedError) as exc:
            await message.answer(escape(str(exc)))
            return
        except TelegramAPIError:
            await message.answer("دریافت عکس کامل نشد؛ لطفاً دوباره بفرست.")
            return
        await state.clear()
        await message.answer(
            "✅ <b>رسیدت دریافت شد.</b>\n\nبعد از بررسی، نتیجه و لینک اشتراکت در همین چت ارسال می‌شود.",
            reply_markup=_order_keyboard(order_id),
        )

    @router.message(F.photo | F.document)
    async def unbound_receipt(message: Message) -> None:
        await message.answer(
            "📸 برای ارسال رسید، ابتدا خریدت را از «پیگیری خرید» انتخاب کن.",
            reply_markup=_section_keyboard("پیگیری خرید", "orders"),
        )

    @router.callback_query(F.data.startswith("pay:"))
    async def pay_order(callback: CallbackQuery) -> None:
        await payment_view(callback, (callback.data or "").removeprefix("pay:"))

    @router.callback_query(F.data.startswith("paycheck:"))
    async def check_payment(callback: CallbackQuery) -> None:
        await callback.answer()
        text, keyboard = await payment_result(
            callback.from_user.id, (callback.data or "").removeprefix("paycheck:")
        )
        await _show_view(callback, text, keyboard)

    @router.callback_query(F.data == "orders")
    async def orders(callback: CallbackQuery) -> None:
        await callback.answer()
        text, keyboard = await order_view(callback.from_user.id)
        await _show_view(callback, text, keyboard)

    @router.callback_query(F.data == "subscriptions")
    async def subscriptions(callback: CallbackQuery) -> None:
        await callback.answer()
        await _show_view(
            callback,
            await subscription_text(callback.from_user.id),
            _subscriptions_keyboard(await service.list_services(callback.from_user.id)),
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
            await callback.answer(
                "مصرف سرویس تازه نیست؛ کمی بعد دوباره امتحان کن.", show_alert=True
            )
            return
        await callback.answer()
        text = (
            f"{RTL}🦋 <b>{escape(access.plan_title)}</b>\n"
            f"{RTL}✅ سرویس فعال\n\n"
            f"{RTL}🔄 <b>اشتراک و مشاهدهٔ مصرف:</b>\n<code>{escape(subscription_url)}</code>\n\n"
            f"{RTL}📊 مصرف: {_size(access.traffic_used_bytes)} از {_size(access.traffic_limit_bytes)}"
            f" · مانده: {_size(access.traffic_remaining_bytes)}\n"
            f"{RTL}🗓 اعتبار تا: {expiry_label(access.expires_at)}\n\n"
            f"{RTL}📲 لینک اشتراک را در برنامهٔ اتصال وارد کن یا QR را اسکن کن.\n"
            f"{RTL}🔐 این لینک‌ها خصوصی‌اند؛ در گروه منتشرشان نکن."
        )
        await _show_view(
            callback, text, _access_keyboard(order_id, subscription_url, bool(access.hysteria_link))
        )

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
        link = next((value for value in links if value.startswith(parts[1] + "://")), None)
        if link is None:
            await callback.answer("این مسیر برای سرویس فعال نیست.", show_alert=True)
            return
        await callback.answer()
        if isinstance(callback.message, Message):
            await callback.message.answer(
                f"{RTL}🔗 <b>{escape(access.profile_name if access else '')}</b>\n\n<code>{escape(link)}</code>\n\n{RTL}🔐 فقط برای استفادهٔ شخصی؛ در گروه منتشر نکن."
            )

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
        await _show_view(
            callback,
            _guide_text(await sales(callback.from_user.id)),
            _section_keyboard("پلن‌ها", "plans"),
        )

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
                f"{RTL}🧭 برای راه‌اندازی، «راهنمای اتصال» را ببین.\n"
                f"{RTL}🧾 برای وضعیت پرداخت، «پیگیری خرید» را باز کن.\n"
                f"{RTL}🔐 لینک اشتراک و رمزها را در گروه‌های عمومی منتشر نکن."
            )
        await _show_view(callback, text, _section_keyboard("سرویس‌های من", "subscriptions"))

    @router.callback_query(F.data == "about")
    async def about(callback: CallbackQuery) -> None:
        await callback.answer()
        text = (
            f"{RTL}🦋 <b>پاپیلیو | Papilio</b>\n\n"
            f"{RTL}اشتراک حجمی، خرید ساده و مدیریت مصرف؛ همه در همین چت.\n\n"
            f"{RTL}📦 پلن دلخواهت را انتخاب کن.\n"
            f"{RTL}🔗 لینک و QR اختصاصی‌ات را بگیر.\n"
            f"{RTL}📊 حجم باقی‌مانده و اعتبارت را ببین.\n"
            + (
                f"{RTL}💳 <i>پرداخت کارت‌به‌کارت</i>"
                if await sales(callback.from_user.id)
                else f"{RTL}🧪 <i>خرید عمومی هنوز باز نیست؛ سرویس‌های فعال قابل استفاده‌اند.</i>"
            )
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
