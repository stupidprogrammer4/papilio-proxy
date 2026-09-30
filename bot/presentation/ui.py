from __future__ import annotations

from hashlib import sha256
from html import escape
from pathlib import Path

from aiogram import F, Router
from aiogram.enums import ChatAction, ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.core.config import Settings
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
BANNER_PATH = ASSETS_DIR / "papilio-banner.png"
LOGO_PATH = ASSETS_DIR / "papilio-logo.png"


def _key(code: str) -> str:
    """Keep administrator-defined plan codes inside Telegram's callback limit."""
    return sha256(code.encode("utf-8")).hexdigest()[:20]


def _home_text(name: str) -> str:
    return (
        f"{RTL}سلام {escape(name)} 👋\n\n"
        f"{RTL}<b>به پاپیلیو خوش اومدی 🦋</b>\n"
        f"{RTL}اینجا می‌تونی پلن‌های موجود رو ببینی و درخواست‌ها و سرویس‌هات رو پیگیری کنی.\n\n"
        f"{RTL}از منوی زیر شروع کن:"
    )


async def _show_welcome(message: Message, name: str) -> None:
    if message.bot is not None:
        await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)
    if BANNER_PATH.is_file():
        await message.answer_photo(FSInputFile(BANNER_PATH), caption=f"{RTL}<b>پاپیلیو 🦋</b>")
    if message.bot is not None:
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await message.answer(_home_text(name), reply_markup=_home_keyboard())


def _toman(value: int) -> str:
    return f"{value:,}".replace(",", "٬") + " تومان"


def _size(value: int) -> str:
    if value < 1024**3:
        return f"{value / 1024**2:.0f} مگابایت"
    return f"{value / 1024**3:.1f}".rstrip("0").rstrip(".") + " گیگابایت"


def _plan_card(plan: Plan) -> str:
    return (
        f"{RTL}<b>{escape(plan.title)}</b>\n"
        f"{RTL}📦 {plan.traffic_gb} گیگابایت  ·  🗓 {plan.duration_days} روز\n"
        f"{RTL}💳 {_toman(plan.price_toman)}"
    )


def _subscription_card(record: Subscription, plan: Plan | None) -> str:
    state = {
        SubscriptionStatus.ACTIVE: "🟢 فعال",
        SubscriptionStatus.PENDING_PAYMENT: "🟡 درخواست ثبت‌شده؛ پرداخت تأیید نشده",
        SubscriptionStatus.EXPIRED: "⚪️ منقضی شده",
        SubscriptionStatus.SUSPENDED: "🔴 متوقف شده",
    }[record.status]
    if record.status == SubscriptionStatus.PENDING_PAYMENT:
        return (
            f"{RTL}<b>{escape(plan.title) if plan else 'پلن آرشیوی'}</b> · {state}\n"
            f"{RTL}شناسهٔ پیگیری: <code>{escape(record.id[:8])}</code>\n"
            f"{RTL}مبلغ ثبت‌شده: {_toman(record.price_rial // 10)}\n"
            f"{RTL}این درخواست هنوز سرویس فعال یا لینک اتصال ندارد."
        )
    expiry = (
        record.expires_at.astimezone().strftime("%Y/%m/%d") if record.expires_at else "ثبت نشده"
    )
    return (
        f"{RTL}<b>{escape(plan.title) if plan else 'پلن آرشیوی'}</b> · {state}\n"
        f"{RTL}📊 مصرف: {_size(record.traffic_used_bytes)} از {_size(record.traffic_limit_bytes)}\n"
        f"{RTL}✨ مانده: <b>{_size(record.traffic_remaining_bytes)}</b>\n"
        f"{RTL}🗓 انقضا: {expiry}"
    )


def _home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🪄 انتخاب پلن", callback_data="plans")],
            [InlineKeyboardButton(text="📊 سرویس‌های من", callback_data="subscriptions")],
            [
                InlineKeyboardButton(text="📚 راهنمای اتصال", callback_data="guide"),
                InlineKeyboardButton(text="💬 پشتیبانی", callback_data="support"),
            ],
            [InlineKeyboardButton(text="🦋 دربارهٔ پاپیلیو", callback_data="about")],
        ]
    )


def _plans_keyboard(plans: list[Plan], page: int = 0) -> InlineKeyboardMarkup:
    page = min(max(page, 0), max(0, (len(plans) - 1) // PAGE_SIZE))
    rows = [
        [
            InlineKeyboardButton(
                text=f"{plan.title} · {plan.traffic_gb} گیگ · {_toman(plan.price_toman)}",
                callback_data=f"plan:{_key(plan.code)}",
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
    rows.append([InlineKeyboardButton(text="↩️ خانه", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _protocol_keyboard(plan_code: str) -> InlineKeyboardMarkup:
    key = _key(plan_code)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="انتخاب VLESS", callback_data=f"order:{key}:vless")],
            [InlineKeyboardButton(text="انتخاب VMess", callback_data=f"order:{key}:vmess")],
            [InlineKeyboardButton(text="↩️ بازگشت به پلن‌ها", callback_data="plans")],
        ]
    )


def _plans_text(plans: list[Plan], page: int) -> str:
    pages = max(1, (len(plans) + PAGE_SIZE - 1) // PAGE_SIZE)
    visible = plans[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    return (
        f"{RTL}<b>پلن‌های موجود</b> · صفحهٔ {page + 1} از {pages}\n"
        f"{RTL}مبلغ‌ها به تومان نمایش داده می‌شوند.\n\n"
        + "\n\n".join(_plan_card(plan) for plan in visible)
        + f"\n\n{RTL}برای جزئیات و ثبت درخواست، روی پلن بزن."
    )


def _guide_text() -> str:
    return (
        f"{RTL}<b>راهنمای اتصال</b> 📚\n\n"
        f"{RTL}۱. پس از فعال‌شدن سرویس، لینک اشتراک اختصاصی‌ات را دریافت کن.\n"
        f"{RTL}۲. لینک را در برنامه‌ای که از نوع اتصال سرویس پشتیبانی می‌کند وارد کن.\n"
        f"{RTL}۳. برای دریافت تغییرات، اشتراک را در همان برنامه به‌روزرسانی کن.\n\n"
        f"{RTL}🔒 لینک اشتراک شخصی است؛ آن را با دیگران به اشتراک نگذار.\n"
        f"{RTL}تحویل خودکار لینک هنوز فعال نشده است."
    )


async def _show_view(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    if message.photo:
        # Text views can exceed Telegram's photo-caption limit.
        await message.edit_reply_markup(reply_markup=None)
        await message.answer(text, reply_markup=keyboard)
    else:
        await message.edit_text(text, reply_markup=keyboard)


def build_router(service: SubscriptionService, settings: Settings) -> Router:
    router = Router(name="papilio")
    router.message.filter(F.chat.type == ChatType.PRIVATE)
    router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

    async def selected_plan(key: str) -> Plan:
        for plan in await service.list_plans():
            if _key(plan.code) == key:
                return plan
        raise UnknownPlanError(key)

    async def subscription_text(telegram_id: int) -> str:
        records = await service.list_subscriptions(telegram_id)
        if not records:
            return f"{RTL}<b>سرویس‌های من</b>\n\n{RTL}هنوز درخواست یا سرویسی ثبت نشده است."
        plans_by_code = {plan.code: plan for plan in await service.list_plans(active_only=False)}
        body = f"{RTL}<b>سرویس‌ها و درخواست‌های من</b>\n\n" + "\n\n".join(
            _subscription_card(item, plans_by_code.get(item.plan_code)) for item in records[:8]
        )
        if len(records) > 8:
            body += f"\n\n{RTL}۸ مورد تازه نمایش داده شد."
        return body

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        sender = message.from_user
        if sender:
            await service.register_user(
                TelegramUser(sender.id, sender.full_name or "کاربر پاپیلیو", sender.username)
            )
        name = sender.first_name if sender else "دوست عزیز"
        await _show_welcome(message, name)

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        await message.answer(_guide_text(), reply_markup=_home_keyboard())

    @router.message(Command("plans"))
    async def plans_command(message: Message) -> None:
        available_plans = await service.list_plans()
        if not available_plans:
            await message.answer(
                f"{RTL}<b>فعلاً پلن فعالی نمایش داده نمی‌شود.</b>\n{RTL}بعداً دوباره سر بزن.",
                reply_markup=_home_keyboard(),
            )
            return
        await message.answer(
            _plans_text(available_plans, 0),
            reply_markup=_plans_keyboard(available_plans),
        )

    @router.message(Command("myservices", "subscriptions"))
    async def subscriptions_command(message: Message) -> None:
        if message.from_user:
            await message.answer(
                await subscription_text(message.from_user.id), reply_markup=_home_keyboard()
            )

    @router.callback_query(F.data == "home")
    async def home(callback: CallbackQuery) -> None:
        await callback.answer()
        await _show_view(callback, _home_text(callback.from_user.first_name), _home_keyboard())

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
                f"{RTL}<b>فعلاً پلن فعالی نمایش داده نمی‌شود.</b>\n{RTL}بعداً دوباره سر بزن.",
                _home_keyboard(),
            )
            return
        page = min(int(raw_page), (len(available_plans) - 1) // PAGE_SIZE)
        await _show_view(
            callback,
            _plans_text(available_plans, page),
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
            f"{RTL}<b>جزئیات پلن</b>\n\n{_plan_card(plan)}\n\n"
            f"{RTL}<b>نوع اتصال را انتخاب کن</b>\n"
            f"{RTL}ثبت درخواست در حال حاضر پرداخت یا فعال‌سازی سرویس را انجام نمی‌دهد.",
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
            order = await service.create_order(callback.from_user.id, plan.code, protocol)
        except (UnknownPlanError, ValueError):
            await callback.answer("درخواست معتبر نیست.", show_alert=True)
            return
        await callback.answer("درخواست ثبت شد")
        await _show_view(
            callback,
            f"{RTL}<b>درخواست ثبت شد</b> 📝\n\n"
            f"{RTL}پلن: {escape(plan.title)} · {protocol.value.upper()}\n"
            f"{RTL}مبلغ: {_toman(order.price_rial // 10)}\n"
            f"{RTL}شناسهٔ پیگیری: <code>{escape(order.id[:8])}</code>\n\n"
            f"{RTL}پرداخت در بات فعال نیست. این درخواست به معنی خرید، تأیید پرداخت یا فعال‌شدن سرویس نیست."
            f"\n{RTL}برای پیگیری، از بخش «سرویس‌های من» استفاده کن.",
            _home_keyboard(),
        )

    @router.callback_query(F.data == "subscriptions")
    async def subscriptions(callback: CallbackQuery) -> None:
        await callback.answer()
        await _show_view(callback, await subscription_text(callback.from_user.id), _home_keyboard())

    @router.callback_query(F.data == "guide")
    async def guide(callback: CallbackQuery) -> None:
        await callback.answer()
        await _show_view(callback, _guide_text(), _home_keyboard())

    @router.callback_query(F.data == "support")
    async def support(callback: CallbackQuery) -> None:
        await callback.answer()
        destination = (
            f"@{escape(settings.support_username)}"
            if settings.support_username
            else "پشتیبانی هنوز تنظیم نشده است"
        )
        await _show_view(
            callback, f"{RTL}<b>پشتیبانی</b> 💬\n\n{RTL}{destination}", _home_keyboard()
        )

    # Handler registration continues with the about view below.
    @router.callback_query(F.data == "about")
    async def about(callback: CallbackQuery) -> None:
        await callback.answer("🦋 پاپیلیو")
        text = (
            f"{RTL}<b>پاپیلیو 🦋</b>\n\n"
            f"{RTL}پنلی ساده برای دیدن پلن‌های موجود و پیگیری وضعیت درخواست و سرویس.\n"
            f"{RTL}امکانات پرداخت و تحویل لینک هنوز در حال آماده‌سازی‌اند."
        )
        if isinstance(callback.message, Message) and LOGO_PATH.is_file():
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer_photo(
                FSInputFile(LOGO_PATH),
                caption=text,
                reply_markup=_home_keyboard(),
            )
            return
        await _show_view(callback, text, _home_keyboard())

    return router
