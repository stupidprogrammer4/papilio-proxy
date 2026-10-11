import asyncio
from typing import Any

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

from papilio_telegram.api import BotApi, BotApiError
from papilio_telegram.checkout import CheckoutDraftLimits, CheckoutDrafts
from papilio_telegram.checkout_handlers import register_checkout, show_offer
from papilio_telegram.presentation import (
    fa,
    gibibytes,
    loyalty_text,
    menu,
    payment_instruction_menu,
    payment_instruction_text,
    plan_menu,
    price_text,
    purchase_menu,
    renewal_status_text,
    service_menu,
    subscription_menu,
    toman,
    trial_service_menu,
    trial_subscription_text,
    trial_text,
    wallet_menu,
)
from papilio_telegram.privacy import PrivateChatGuard
from papilio_telegram.topups import TopupFlowLimits

_ERRORS = {
    "purchase_price_changed": (
        "قیمت نهایی تغییر کرده است. همین پلن را دوباره باز کنید "
        "و قیمت تازه را بررسی کنید."
    ),
    "payment_destination_required": (
        "برای انتخاب مقصد پرداخت و ارسال رسید، "
        "«حساب کاربری و رسیدها» را باز کنید."
    ),
    "topup_amount_policy": "مبلغ شارژ خارج از بازهٔ مجاز است.",
    "customer_unauthorized": (
        "حساب شما غیرفعال است یا ورود فعلاً در دسترس نیست."
    ),
    "wallet_insufficient": (
        "موجودی کیف پول کافی نیست. ابتدا درخواست شارژ ثبت کنید."
    ),
    "plan_inactive": "این پلن دیگر برای خرید فعال نیست.",
    "subscription_not_found": "این اشتراک در حساب شما پیدا نشد.",
    "network": "ارتباط با سرویس برقرار نشد. کمی بعد دوباره تلاش کنید.",
}


def identity(user: User) -> tuple[int, str]:
    return user.id, (user.full_name or "کاربر تلگرام")[:120]


def register(
    api: BotApi,
    checkout_limits: CheckoutDraftLimits | None = None,
    topup_limits: TopupFlowLimits | None = None,
) -> Router:
    router = Router()
    guard = PrivateChatGuard()
    router.message.outer_middleware(guard)
    router.callback_query.outer_middleware(guard)
    drafts = CheckoutDrafts(checkout_limits) if checkout_limits else None
    if drafts is not None:
        router.include_router(register_checkout(api, drafts))

    async def say(
        callback: CallbackQuery,
        text: str,
        keyboard: Any = None,
        parse_mode: str | None = None,
    ) -> None:
        if isinstance(callback.message, Message):
            await callback.message.answer(
                text, reply_markup=keyboard, parse_mode=parse_mode
            )
        await callback.answer()

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        if message.from_user is None:
            return
        telegram_id, name = identity(message.from_user)
        try:
            home = await api.home(telegram_id, name)
            greeting = (
                f"سلام {home['display_name']} 🌿\n"
                f"به {home['brand_title']} خوش آمدید.\n"
                f"💰 موجودی کیف پول: {toman(int(home['balance_rial']))}"
            )
            await message.answer(
                greeting,
                reply_markup=menu(),
            )
        except BotApiError as exc:
            await message.answer(
                _ERRORS.get(exc.code, "درخواست انجام نشد. دوباره تلاش کنید.")
            )

    @router.callback_query(F.data == "home")
    async def home(callback: CallbackQuery) -> None:
        telegram_id, name = identity(callback.from_user)
        try:
            result = await api.home(telegram_id, name)
            text = (
                f"🦋 {result['brand_title']}\n\n"
                f"💰 موجودی کیف پول: {toman(int(result['balance_rial']))}"
            )
            await say(
                callback,
                text,
                menu(),
            )
        except BotApiError as exc:
            await say(callback, _ERRORS.get(exc.code, "درخواست انجام نشد."))

    @router.callback_query(F.data == "loyalty")
    async def loyalty(callback: CallbackQuery) -> None:
        telegram_id, name = identity(callback.from_user)
        try:
            result = await api.loyalty(telegram_id, name)
            await say(callback, loyalty_text(result), menu())
        except BotApiError as exc:
            await say(
                callback,
                _ERRORS.get(
                    exc.code,
                    "امتیاز خرید دریافت نشد؛ دوباره از همین بخش تلاش کنید.",
                ),
                menu(),
            )

    @router.callback_query(F.data.startswith("plans:"))
    async def plans(callback: CallbackQuery) -> None:
        page = int((callback.data or "plans:1").split(":")[1])
        telegram_id, name = identity(callback.from_user)
        try:
            result = await api.plans(telegram_id, name, page)
            rows = result["data"]
            pages = (
                result.get("meta", {})
                .get("pager", {})
                .get("total_pages", page)
            )
            text = (
                "پلن‌های قابل خرید:" if rows else "فعلاً پلن فعالی ثبت نشده است."
            )
            await say(callback, text, plan_menu(rows, page, pages))
        except BotApiError as exc:
            await say(callback, _ERRORS.get(exc.code, "پلن‌ها دریافت نشدند."))

    @router.callback_query(F.data.startswith("plan:"))
    async def plan(callback: CallbackQuery) -> None:
        plan_id = int((callback.data or "plan:0").split(":")[1])
        telegram_id, name = identity(callback.from_user)
        try:
            if drafts is not None:
                try:
                    await show_offer(api, drafts, callback, plan_id)
                    return
                except BotApiError as exc:
                    if exc.code != "checkout_disabled":
                        raise
            detail, quote = await asyncio.gather(
                api.plan(plan_id, telegram_id, name),
                api.price_quote(plan_id, telegram_id, name),
            )
            await say(
                callback,
                (
                    f"{detail['title']}\n" + price_text(quote) + "\n"
                    "مدت: "
                    + (
                        "بدون مدت"
                        if detail["duration_days"] is None
                        else fa(detail["duration_days"]) + " روز"
                    )
                    + "\nحجم: "
                    + (
                        "نامحدود"
                        if detail["quota_bytes"] is None
                        else gibibytes(int(detail["quota_bytes"]))
                    )
                    + "\n"
                    + "خرید از موجودی کیف پول انجام می‌شود."
                ),
                purchase_menu(plan_id, quote.price_rial),
            )
        except BotApiError as exc:
            await say(callback, _ERRORS.get(exc.code, "پلن دریافت نشد."))

    @router.callback_query(F.data.startswith("buy:"))
    async def buy(callback: CallbackQuery) -> None:
        parts = (callback.data or "buy:0:0").split(":")
        _, id_text, renewal_text = parts[:3]
        price = int(parts[3]) if len(parts) == 4 else None
        telegram_id, name = identity(callback.from_user)
        message_id = (
            str(callback.message.message_id)
            if isinstance(callback.message, Message)
            else callback.id
        )
        purchase_key = (
            f"tg:{telegram_id}:{message_id}:{id_text}:{renewal_text}"
        )
        try:
            if drafts is not None:
                try:
                    await show_offer(api, drafts, callback, int(id_text))
                    return
                except BotApiError as exc:
                    if exc.code != "checkout_disabled":
                        raise
            result = await api.purchase(
                telegram_id,
                name,
                int(id_text),
                renewal_text == "1",
                purchase_key,
                price,
            )
            await say(
                callback,
                f"خرید شمارهٔ {fa(result['id'])} ثبت شد.\n"
                "سرویس پس از راه‌اندازی نود فعال می‌شود. "
                "وضعیت را از «سرویس‌های من» پیگیری کنید.",
                menu(),
            )
        except BotApiError as exc:
            text = _ERRORS.get(exc.code, "خرید انجام نشد. دوباره تلاش کنید.")
            keyboard = menu()
            if exc.code == "network":
                text = (
                    "نتیجهٔ خرید هنوز مشخص نیست. برای پیگیری امن، "
                    "همان دکمهٔ خرید در پیام قبلی را دوباره بزنید."
                )
            elif exc.code == "purchase_price_changed":
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="بررسی قیمت تازهٔ همین پلن",
                                callback_data=f"plan:{id_text}",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text="↩️ بازگشت", callback_data="home"
                            )
                        ],
                    ]
                )
            await say(callback, text, keyboard)

    @router.callback_query(F.data == "trial")
    async def trial(callback: CallbackQuery) -> None:
        telegram_id, name = identity(callback.from_user)
        try:
            offer = await api.trial_availability(telegram_id, name)
            keyboard = (
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="دریافت آزمایشی رایگان",
                                callback_data="trial_claim",
                            )
                        ]
                    ]
                )
                if offer.eligible
                else menu()
            )
            await say(
                callback,
                trial_text(offer),
                keyboard,
            )
        except BotApiError as exc:
            await say(
                callback, _ERRORS.get(exc.code, "شرایط آزمایشی دریافت نشد.")
            )

    @router.callback_query(F.data == "trial_claim")
    async def trial_claim(callback: CallbackQuery) -> None:
        telegram_id, name = identity(callback.from_user)
        if not isinstance(callback.message, Message):
            await callback.answer(
                "پیام دریافت آزمایشی را دوباره باز کنید.", show_alert=True
            )
            return
        message_id = str(callback.message.message_id)
        try:
            result = await api.trial_claim(
                telegram_id, name, f"telegram-trial:{message_id}"
            )
            await say(
                callback,
                trial_subscription_text(result),
                trial_service_menu(result.id),
            )
        except BotApiError as exc:
            await say(
                callback,
                "نتیجهٔ درخواست هنوز مشخص نیست؛ همان دکمهٔ دریافت "
                "در پیام قبلی را دوباره بزنید."
                if exc.code == "network"
                else _ERRORS.get(
                    exc.code, "دریافت آزمایشی با شرایط فعلی ممکن نیست."
                ),
            )

    @router.callback_query(F.data == "account")
    async def account(callback: CallbackQuery) -> None:
        telegram_id, name = identity(callback.from_user)
        try:
            result = await api.account_link(telegram_id, name)
            await say(
                callback,
                (
                    "🔐 لینک خصوصی حساب شما فقط یک بار استفاده می‌شود. "
                    "آن را برای دیگران نفرستید. "
                    "خرید، شارژ و ارسال رسید از حساب قابل انجام است."
                ),
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="ورود به حساب کاربری", url=result["url"]
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text="↩️ بازگشت", callback_data="home"
                            )
                        ],
                    ]
                ),
            )
        except BotApiError as exc:
            await say(callback, _ERRORS.get(exc.code, "لینک ورود دریافت نشد."))

    @router.callback_query(F.data == "wallet")
    async def wallet(callback: CallbackQuery) -> None:
        telegram_id, name = identity(callback.from_user)
        try:
            result = await api.home(telegram_id, name)
            await say(
                callback,
                "💳 کیف پول شما\n\n"
                f"موجودی: {toman(int(result['balance_rial']))}\n"
                "✅ پس از تأیید واریز، مبلغ به کیف پول شما اضافه می‌شود.",
                wallet_menu(result["topup_options_rial"]),
            )
        except BotApiError as exc:
            await say(callback, _ERRORS.get(exc.code, "کیف پول دریافت نشد."))

    @router.callback_query(F.data.startswith("topup:"))
    async def topup(callback: CallbackQuery) -> None:
        amount = int((callback.data or "topup:0").split(":")[1])
        telegram_id, name = identity(callback.from_user)
        try:
            message_id = (
                str(callback.message.message_id)
                if isinstance(callback.message, Message)
                else callback.id
            )
            result = await api.topup(
                telegram_id,
                name,
                amount,
                f"tg:{telegram_id}:{message_id}:{amount}",
            )
            instruction = await api.topup_instruction(
                result["id"], telegram_id, name
            )
            if instruction is None:
                await say(
                    callback,
                    f"🧾 درخواست شارژ شمارهٔ {fa(result['id'])} ثبت شد.\n\n"
                    "اطلاعات واریز اختصاصی در دسترس نیست؛ قبل از واریز، "
                    "مبلغ و مقصد را از حساب کاربری بررسی کنید.",
                    menu(),
                )
            else:
                await say(
                    callback,
                    payment_instruction_text(instruction),
                    payment_instruction_menu(instruction, menu()),
                    parse_mode="HTML",
                )
        except BotApiError as exc:
            await say(
                callback,
                _ERRORS.get(exc.code, "درخواست شارژ ثبت نشد."),
                menu(),
            )

    @router.callback_query(F.data.startswith("subs:"))
    async def subscriptions(callback: CallbackQuery) -> None:
        page = int((callback.data or "subs:1").split(":")[1])
        telegram_id, name = identity(callback.from_user)
        try:
            result = await api.subscriptions(telegram_id, name, page)
            rows = result["data"]
            pages = (
                result.get("meta", {})
                .get("pager", {})
                .get("total_pages", page)
            )
            text = (
                "📱 سرویس‌های شما\n\nبرای دریافت کانفیگ و مدیریت تمدید "
                "روی هر مورد بزنید."
                if rows
                else "📱 هنوز سرویسی ندارید؛ از بخش خرید سرویس شروع کنید."
            )
            await say(callback, text, subscription_menu(rows, page, pages))
        except BotApiError as exc:
            await say(callback, _ERRORS.get(exc.code, "سرویس‌ها دریافت نشدند."))

    @router.callback_query(
        F.data.startswith("service:") | F.data.startswith("rotate:")
    )
    async def service(callback: CallbackQuery) -> None:
        action, id_text = (callback.data or "service:0").split(":")
        telegram_id, name = identity(callback.from_user)
        try:
            result = await api.delivery(
                telegram_id, name, int(id_text), rotate=action == "rotate"
            )
            labels = {
                "revoking": "در انتظار ابطال",
                "exhausted": "سهمیه تمام‌شده",
                "suspended": "تعلیق‌شده",
                "active": "فعال",
                "pending_provision": "در انتظار راه‌اندازی",
                "failed": "راه‌اندازی ناموفق",
                "expired": "منقضی",
                "cancelled": "لغوشده",
            }
            status = labels.get(result["status"], "نیازمند بررسی")
            text = f"📱 اشتراک {fa(result['subscription_id'])} · {status}"
            if action == "rotate":
                text += (
                    "\nلینک خصوصی عوض شد. لینک قبلی دیگر قابل استفاده نیست."
                )
            await say(callback, text, service_menu(result))
        except BotApiError as exc:
            await say(
                callback, _ERRORS.get(exc.code, "اطلاعات سرویس دریافت نشد.")
            )

    @router.callback_query(F.data.startswith("renewal-status:"))
    async def renewal_status(callback: CallbackQuery) -> None:
        telegram_id, name = identity(callback.from_user)
        try:
            result = await api.renewal_eligibility(
                telegram_id,
                name,
                int((callback.data or "renewal-status:0").split(":")[1]),
            )
            await say(
                callback,
                renewal_status_text(result),
                trial_service_menu(result.subscription_id),
            )
        except BotApiError as exc:
            await say(
                callback,
                _ERRORS.get(
                    exc.code, "وضعیت تمدید دریافت نشد؛ دوباره بررسی کنید."
                ),
            )

    @router.callback_query(F.data.startswith("renew:"))
    async def auto_renew(callback: CallbackQuery) -> None:
        _, id_text, enabled_text = (callback.data or "renew:0:0").split(":")
        telegram_id, name = identity(callback.from_user)
        try:
            result = await api.auto_renew(
                telegram_id, name, int(id_text), enabled_text == "1"
            )
            state = "روشن" if result["auto_renew"] else "خاموش"
            await say(
                callback,
                f"🔄 تمدید خودکار اشتراک {fa(result['id'])} {state} شد.",
                menu(),
            )
        except BotApiError as exc:
            await say(
                callback, _ERRORS.get(exc.code, "تغییر تمدید انجام نشد.")
            )

    @router.callback_query(F.data == "support")
    async def support(callback: CallbackQuery) -> None:
        telegram_id, name = identity(callback.from_user)
        try:
            link = await api.support_link(telegram_id, name)
            if link["status"] == "portal":
                await say(
                    callback,
                    "از این لینک خصوصی برای ثبت تیکت "
                    "و ادامهٔ گفتگو استفاده کنید. "
                    "لینک ورود کوتاه‌مدت و یک‌بارمصرف است.",
                    InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="تیکت‌های پشتیبانی", url=link["url"]
                                )
                            ],
                            [
                                InlineKeyboardButton(
                                    text="↩️ بازگشت", callback_data="home"
                                )
                            ],
                        ]
                    ),
                )
            elif link["status"] == "contact":
                await say(
                    callback,
                    "ورود به پنل پشتیبانی فعلاً در دسترس نیست. "
                    f"راه ارتباط پشتیبانی: {link['support_handle']}",
                    menu(),
                )
            else:
                await say(
                    callback,
                    "ورود به پنل پشتیبانی در دسترس نیست "
                    "و راه ارتباط جایگزین هنوز تنظیم نشده است.",
                    menu(),
                )
        except BotApiError as exc:
            await say(
                callback, _ERRORS.get(exc.code, "اطلاعات پشتیبانی دریافت نشد.")
            )

    return router
