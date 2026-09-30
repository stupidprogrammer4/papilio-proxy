from __future__ import annotations

from pathlib import Path

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import CommandStart
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
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"
BANNER_PATH = ASSETS_DIR / "papilio-banner.png"

LOGO_PATH = ASSETS_DIR / "papilio-logo.png"


def _home_text(name: str) -> str:
    return (
        f"{RTL}سلام {name} ✨\n\n"
        f"{RTL}<b>به پاپیلیو خوش اومدی.</b>\n"
        f"{RTL}سرویس شخصی، ساده و همیشه قابل‌مدیریت؛ از انتخاب پلن تا دیدن مصرف، همه همین‌جاست.\n\n"
        f"{RTL}🌈 <b>حجم شفاف</b>  •  ⚡ <b>تحویل امن</b>  •  🫶 <b>پشتیبانی کنار تو</b>\n\n"
        f"{RTL}از پایین شروع کن 👇"
    )


async def _show_welcome(message: Message, name: str) -> None:
    if message.bot is not None:
        await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)
    if BANNER_PATH.is_file():
        await message.answer_photo(
            FSInputFile(BANNER_PATH), caption=f"{RTL}🦋 <b>پاپیلیو</b> • اینترنت شخصی تو"
        )
    if message.bot is not None:
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await message.answer(_home_text(name), reply_markup=_home_keyboard())


def _toman(value: int) -> str:
    return f"{value:,}".replace(",", "٬") + " تومان"


def _size(value: int) -> str:
    return f"{value / 1024**3:.1f}".rstrip("0").rstrip(".") + " گیگابایت"


def _plan_card(plan: Plan) -> str:
    return (
        f"{RTL}┏━ <b>{plan.title}</b>\n"
        f"{RTL}┃ 📦 {plan.traffic_gb} گیگابایت حجم\n"
        f"{RTL}┃ 🗓 اعتبار {plan.duration_days} روز\n"
        f"{RTL}┃ 💳 {_toman(plan.price_toman)}\n"
        f"{RTL}┗━ مناسب استفادهٔ روزمره و بی‌دردسر"
    )


def _subscription_card(record: Subscription, plan: Plan | None) -> str:
    state = {
        SubscriptionStatus.ACTIVE: "🟢 فعال",
        SubscriptionStatus.PENDING_PAYMENT: "🟡 در انتظار تأیید پرداخت",
        SubscriptionStatus.EXPIRED: "⚪️ منقضی شده",
        SubscriptionStatus.SUSPENDED: "🔴 متوقف شده",
    }[record.status]
    expiry = (
        record.expires_at.astimezone().strftime("%Y/%m/%d")
        if record.expires_at
        else "پس از پرداخت تعیین می‌شود"
    )
    return (
        f"{RTL}<b>{plan.title if plan else 'پلن آرشیوی'}</b>\n{RTL}{state}\n\n"
        f"{RTL}📊 مصرف: {_size(record.traffic_used_bytes)} از {_size(record.traffic_limit_bytes)}\n"
        f"{RTL}✨ مانده: <b>{_size(record.traffic_remaining_bytes)}</b>\n"
        f"{RTL}🗓 انقضا: {expiry}"
    )


def _home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🪄 انتخاب پلن", callback_data="plans")],
            [InlineKeyboardButton(text="📊 سرویس‌های من", callback_data="subscriptions")],
            [InlineKeyboardButton(text="📚 راهنمای اتصال", callback_data="guide")],
            [InlineKeyboardButton(text="🦋 دربارهٔ پاپیلیو", callback_data="about")],
            [InlineKeyboardButton(text="💬 پشتیبانی", callback_data="support")],
        ]
    )


def _plans_keyboard(plans: list[Plan]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{plan.title}  •  {plan.traffic_gb} گیگ  •  {_toman(plan.price_toman)}",
                callback_data=f"plan:{plan.code}",
            )
        ]
        for plan in plans
    ]
    rows.append([InlineKeyboardButton(text="↩️ خانه", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _protocol_keyboard(plan_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✨ VLESS + REALITY  •  پیشنهادی", callback_data=f"order:{plan_code}:vless"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔷 VMess  •  سازگار", callback_data=f"order:{plan_code}:vmess"
                )
            ],
            [InlineKeyboardButton(text="↩️ بازگشت به پلن‌ها", callback_data="plans")],
        ]
    )


def build_router(service: SubscriptionService, settings: Settings) -> Router:
    router = Router(name="papilio")

    async def edit(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup) -> None:
        if isinstance(callback.message, Message):
            await callback.message.edit_text(text, reply_markup=keyboard)

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        sender = message.from_user
        if sender:
            await service.register_user(
                TelegramUser(sender.id, sender.full_name or "کاربر پاپیلیو", sender.username)
            )
        name = sender.first_name if sender else "دوست عزیز"
        await _show_welcome(message, name)

    @router.callback_query(F.data == "home")
    async def home(callback: CallbackQuery) -> None:
        await callback.answer()
        await edit(callback, _home_text(callback.from_user.first_name), _home_keyboard())

    @router.callback_query(F.data == "plans")
    async def plans(callback: CallbackQuery) -> None:
        await callback.answer()
        available_plans = await service.list_plans()
        if not available_plans:
            await edit(callback, f"{RTL}فعلاً پلن فعالی برای فروش وجود ندارد.", _home_keyboard())
            return
        body = (
            f"{RTL}<b>پلن مناسب خودت را انتخاب کن ✨</b>\n{RTL}هر پلن ۳۰ روز اعتبار دارد و حجم آن شفاف است.\n\n"
            + "\n\n".join(_plan_card(plan) for plan in available_plans)
        )
        await edit(callback, body, _plans_keyboard(available_plans))

    @router.callback_query(F.data.startswith("plan:"))
    async def choose_protocol(callback: CallbackQuery) -> None:
        data = callback.data
        if data is None:
            await callback.answer("درخواست معتبر نیست.", show_alert=True)
            return
        code = data.split(":", 1)[1]
        try:
            plan = await service.get_plan(code)
        except UnknownPlanError:
            await callback.answer("این پلن دیگر در دسترس نیست.", show_alert=True)
            return
        await callback.answer()
        await edit(
            callback,
            f"{RTL}{_plan_card(plan)}\n\n{RTL}<b>روش اتصال را انتخاب کن</b>\n{RTL}✨ VLESS مسیر پیشنهادی ماست.",
            _protocol_keyboard(code),
        )

    @router.callback_query(F.data.startswith("order:"))
    async def create_order(callback: CallbackQuery) -> None:
        data = callback.data
        if data is None:
            await callback.answer("درخواست معتبر نیست.", show_alert=True)
            return
        _, plan_code, raw_protocol = data.split(":", 2)
        if callback.from_user is None:
            await callback.answer("شناسه کاربر در دسترس نیست.", show_alert=True)
            return
        try:
            protocol = Protocol(raw_protocol)
            order = await service.create_order(callback.from_user.id, plan_code, protocol)
        except (UnknownPlanError, ValueError):
            await callback.answer("درخواست معتبر نیست.", show_alert=True)
            return
        await callback.answer("درخواست ثبت شد")
        plan = await service.get_plan(plan_code)
        await edit(
            callback,
            f"{RTL}درخواست شما ثبت شد ✦\n\n{RTL}{plan.title} با پروتکل {protocol.upper()}\n"
            f"{RTL}شناسه پیگیری: {order.id[:8]}\n\n"
            f"{RTL}درگاه پرداخت در اتصال بعدی فعال می‌شود؛ پس از تأیید پرداخت، لینک سرویس به‌صورت امن همین‌جا ارسال خواهد شد.",
            _home_keyboard(),
        )

    @router.callback_query(F.data == "subscriptions")
    async def subscriptions(callback: CallbackQuery) -> None:
        if callback.from_user is None:
            return
        await callback.answer()
        records = await service.list_subscriptions(callback.from_user.id)
        if not records:
            text = f"{RTL}هنوز سرویسی نداری. از بخش «انتخاب پلن» شروع کن."
        else:
            plans_by_code = {
                plan.code: plan for plan in await service.list_plans(active_only=False)
            }
            text = f"{RTL}سرویس‌های من\n\n" + "\n\n".join(
                _subscription_card(item, plans_by_code.get(item.plan_code)) for item in records
            )
        await edit(callback, text, _home_keyboard())

    @router.callback_query(F.data == "guide")
    async def guide(callback: CallbackQuery) -> None:
        await callback.answer()
        await edit(
            callback,
            f"{RTL}راهنمای اتصال\n\n{RTL}۱. پلن و پروتکل را انتخاب کن.\n"
            f"{RTL}۲. پس از پرداخت، لینک اتصال را دریافت می‌کنی.\n"
            f"{RTL}۳. لینک را در کلاینت سازگار با VLESS یا VMess وارد کن.\n\n"
            f"{RTL}لینک‌ها را با دیگران به اشتراک نگذار.",
            _home_keyboard(),
        )

    @router.callback_query(F.data == "support")
    async def support(callback: CallbackQuery) -> None:
        await callback.answer()
        destination = (
            f"@{settings.support_username}"
            if settings.support_username
            else "پشتیبانی هنوز تنظیم نشده است"
        )
        await edit(callback, f"{RTL}پشتیبانی پاپیلیو\n\n{RTL}{destination}", _home_keyboard())

    # Handler registration continues with the about view below.
    @router.callback_query(F.data == "about")
    async def about(callback: CallbackQuery) -> None:
        await callback.answer("🦋 پاپیلیو")
        text = (
            f"{RTL}<b>پاپیلیو، اینترنت شخصی تو</b>\n\n"
            f"{RTL}اینجا پلن، مصرف و وضعیت سرویس را ساده و شفاف مدیریت می‌کنی.\n"
            f"{RTL}هر زمان به کمک نیاز داشتی، پشتیبانی کنار توست. 💜"
        )
        if isinstance(callback.message, Message) and LOGO_PATH.is_file():
            await callback.message.answer_photo(
                FSInputFile(LOGO_PATH),
                caption=text,
                reply_markup=_home_keyboard(),
            )
            return
        await edit(callback, text, _home_keyboard())

    return router
