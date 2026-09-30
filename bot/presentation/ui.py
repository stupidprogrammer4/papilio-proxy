from __future__ import annotations

from hashlib import sha256
from html import escape
from pathlib import Path

from aiogram import F, Router
from aiogram.enums import ChatType
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
BANNER_PATH = ASSETS_DIR / "papilio-banner-v2.png"
LOGO_PATH = ASSETS_DIR / "papilio-logo-v2.png"
ANIMATION_PATH = ASSETS_DIR / "papilio-intro-v2.mp4"


def _key(code: str) -> str:
    """Keep administrator-defined plan codes inside Telegram's callback limit."""
    return sha256(code.encode("utf-8")).hexdigest()[:20]


def _home_text(name: str) -> str:
    return (
        f"{RTL}<b>پاپیلیو</b>\n"
        f"{RTL}سلام {escape(name)}، خوش آمدی.\n\n"
        f"{RTL}پلن‌ها و وضعیت درخواست‌هایت را از همین‌جا ببین.\n"
        f"{RTL}<i>نسخهٔ پیش‌نمایش · پرداخت و تحویل سرویس هنوز فعال نیست.</i>"
    )


async def _show_welcome(message: Message, name: str) -> None:
    if ANIMATION_PATH.is_file():
        await message.answer_animation(
            FSInputFile(ANIMATION_PATH),
            caption=_home_text(name),
            reply_markup=_home_keyboard(),
        )
    elif BANNER_PATH.is_file():
        await message.answer_photo(
            FSInputFile(BANNER_PATH),
            caption=_home_text(name),
            reply_markup=_home_keyboard(),
        )
    else:
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
        f"{RTL}{plan.traffic_gb} گیگابایت · {plan.duration_days} روز\n"
        f"{RTL}{_toman(plan.price_toman)}"
    )


def _subscription_card(record: Subscription, plan: Plan | None) -> str:
    state = {
        SubscriptionStatus.ACTIVE: "فعال",
        SubscriptionStatus.PENDING_PAYMENT: "ثبت اولیه · پرداخت تأیید نشده",
        SubscriptionStatus.EXPIRED: "منقضی‌شده",
        SubscriptionStatus.SUSPENDED: "متوقف‌شده",
    }[record.status]
    if record.status == SubscriptionStatus.PENDING_PAYMENT:
        return (
            f"{RTL}<b>{escape(plan.title) if plan else 'پلن آرشیوی'}</b> · {state}\n"
            f"{RTL}شناسهٔ پیگیری: <code>{escape(record.id[:8])}</code>\n"
            f"{RTL}مبلغ: {_toman(record.price_rial // 10)}"
        )
    expiry = (
        record.expires_at.astimezone().strftime("%Y/%m/%d") if record.expires_at else "ثبت نشده"
    )
    return (
        f"{RTL}<b>{escape(plan.title) if plan else 'پلن آرشیوی'}</b> · {state}\n"
        f"{RTL}مصرف: {_size(record.traffic_used_bytes)} از {_size(record.traffic_limit_bytes)}\n"
        f"{RTL}مانده: {_size(record.traffic_remaining_bytes)} · انقضا: {expiry}"
    )


def _home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="پلن‌ها", callback_data="plans", style="primary")],
            [
                InlineKeyboardButton(
                    text="سرویس‌های من",
                    callback_data="subscriptions",
                    style="success",
                )
            ],
            [
                InlineKeyboardButton(text="راهنما", callback_data="guide"),
                InlineKeyboardButton(text="پشتیبانی", callback_data="support"),
            ],
            [InlineKeyboardButton(text="درباره", callback_data="about")],
        ]
    )


def _section_keyboard(action: str, callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=action, callback_data=callback_data, style="primary"),
                InlineKeyboardButton(text="خانه", callback_data="home"),
            ]
        ]
    )


def _short_title(title: str) -> str:
    return title if len(title) <= 24 else title[:23].rstrip() + "…"


def _plans_keyboard(plans: list[Plan], page: int = 0) -> InlineKeyboardMarkup:
    page = min(max(page, 0), max(0, (len(plans) - 1) // PAGE_SIZE))
    rows = [
        [
            InlineKeyboardButton(
                text=f"جزئیات · {_short_title(plan.title)}",
                callback_data=f"plan:{_key(plan.code)}",
            )
        ]
        for plan in plans[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    ]
    navigation: list[InlineKeyboardButton] = []
    if page:
        navigation.append(InlineKeyboardButton(text="قبلی", callback_data=f"plans:{page - 1}"))
    if (page + 1) * PAGE_SIZE < len(plans):
        navigation.append(InlineKeyboardButton(text="بعدی", callback_data=f"plans:{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton(text="خانه", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _protocol_keyboard(plan_code: str) -> InlineKeyboardMarkup:
    key = _key(plan_code)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="ثبت درخواست · VLESS",
                    callback_data=f"order:{key}:vless",
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(
                    text="ثبت درخواست · VMess",
                    callback_data=f"order:{key}:vmess",
                )
            ],
            [InlineKeyboardButton(text="بازگشت به پلن‌ها", callback_data="plans")],
        ]
    )


def _order_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="پیگیری درخواست",
                    callback_data="subscriptions",
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(text="پلن‌ها", callback_data="plans"),
                InlineKeyboardButton(text="خانه", callback_data="home"),
            ],
        ]
    )


def _plans_text(plans: list[Plan], page: int) -> str:
    pages = max(1, (len(plans) + PAGE_SIZE - 1) // PAGE_SIZE)
    visible = plans[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    return (
        f"{RTL}<b>پلن‌ها</b> · صفحهٔ {page + 1} از {pages}\n\n"
        + "\n\n".join(_plan_card(plan) for plan in visible)
        + f"\n\n{RTL}<i>پرداخت و فعال‌سازی هنوز در دسترس نیست.</i>"
    )


def _guide_text() -> str:
    return (
        f"{RTL}<b>راهنمای اتصال</b>\n\n"
        f"{RTL}پس از فعال‌سازی، لینک اشتراک را در برنامهٔ سازگار وارد کن. "
        f"برای دریافت تغییرات، اشتراک را در برنامه به‌روزرسانی کن.\n\n"
        f"{RTL}لینک اختصاصی است؛ آن را در اختیار دیگران نگذار.\n"
        f"{RTL}<i>تحویل لینک از طریق بات هنوز فعال نیست.</i>"
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


async def _show_home(callback: CallbackQuery) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    name = callback.from_user.first_name
    if message.photo or message.animation:
        await _show_view(callback, _home_text(name), _home_keyboard(), caption_ok=True)
    else:
        await message.edit_reply_markup(reply_markup=None)
        await _show_welcome(message, name)


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
            return f"{RTL}<b>درخواست‌ها و سرویس‌های من</b>\n\n{RTL}هنوز موردی ثبت نشده است."
        plans_by_code = {plan.code: plan for plan in await service.list_plans(active_only=False)}
        body = f"{RTL}<b>سرویس‌ها و درخواست‌های من</b>\n\n" + "\n\n".join(
            _subscription_card(item, plans_by_code.get(item.plan_code)) for item in records[:8]
        )
        if len(records) > 8:
            body += f"\n\n{RTL}۸ مورد تازه نمایش داده شد."
        if any(item.status == SubscriptionStatus.PENDING_PAYMENT for item in records[:8]):
            body += f"\n\n{RTL}<i>درخواست ثبت اولیه هنوز سرویس فعال ندارد.</i>"
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
        await message.answer(_guide_text(), reply_markup=_section_keyboard("پلن‌ها", "plans"))

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
            _plans_text(available_plans, 0),
            reply_markup=_plans_keyboard(available_plans),
        )

    @router.message(Command("myservices", "subscriptions"))
    async def subscriptions_command(message: Message) -> None:
        if message.from_user:
            await message.answer(
                await subscription_text(message.from_user.id),
                reply_markup=_section_keyboard("پلن‌ها", "plans"),
            )

    @router.callback_query(F.data == "home")
    async def home(callback: CallbackQuery) -> None:
        await callback.answer()
        await _show_home(callback)

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
            f"{RTL}{_plan_card(plan)}\n\n"
            f"{RTL}نوع اتصال را برای ثبت اولیهٔ درخواست انتخاب کن.\n"
            f"{RTL}<i>این مرحله پرداخت یا فعال‌سازی نیست.</i>",
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
            f"{RTL}<b>درخواست ثبت شد</b>\n\n"
            f"{RTL}{escape(plan.title)} · {protocol.value.upper()} · {_toman(order.price_rial // 10)}\n"
            f"{RTL}کد پیگیری: <code>{escape(order.id[:8])}</code>\n\n"
            f"{RTL}<i>پرداخت و فعال‌سازی انجام نشده است.</i>",
            _order_keyboard(),
        )

    @router.callback_query(F.data == "subscriptions")
    async def subscriptions(callback: CallbackQuery) -> None:
        await callback.answer()
        await _show_view(
            callback,
            await subscription_text(callback.from_user.id),
            _section_keyboard("پلن‌ها", "plans"),
        )

    @router.callback_query(F.data == "guide")
    async def guide(callback: CallbackQuery) -> None:
        await callback.answer()
        await _show_view(callback, _guide_text(), _section_keyboard("پلن‌ها", "plans"))

    @router.callback_query(F.data == "support")
    async def support(callback: CallbackQuery) -> None:
        await callback.answer()
        if settings.support_username:
            destination = f"@{escape(settings.support_username)}"
            text = (
                f"{RTL}<b>پشتیبانی</b>\n\n"
                f"{RTL}برای پیگیری، کد درخواستت را برای {destination} بفرست."
            )
        else:
            text = f"{RTL}<b>پشتیبانی</b>\n\n{RTL}راه ارتباطی هنوز تنظیم نشده است."
        await _show_view(callback, text, _section_keyboard("سرویس‌های من", "subscriptions"))

    @router.callback_query(F.data == "about")
    async def about(callback: CallbackQuery) -> None:
        await callback.answer()
        text = (
            f"{RTL}<b>پاپیلیو</b>\n\n"
            f"{RTL}انتخاب پلن و پیگیری وضعیت سرویس در یک گفت‌وگو.\n"
            f"{RTL}<i>نسخهٔ فعلی پیش‌نمایش است؛ پرداخت و تحویل سرویس فعال نیست.</i>"
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
