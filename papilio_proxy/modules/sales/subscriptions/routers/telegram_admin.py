from __future__ import annotations

from hashlib import sha256
from html import escape
from typing import Literal

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from papilio_proxy.modules.sales.subscriptions.app.plans import (
    AdminAccessError,
    AdminPlanService,
    PlanValidationError,
)
from papilio_proxy.modules.sales.subscriptions.app.services import Plan, UnknownPlanError

PAGE_SIZE = 8
RTL = "\u200f"


class PlanForm(StatesGroup):
    waiting = State()


def _key(code: str) -> str:
    """Keep callback data below Telegram's 64-byte limit for long plan codes."""
    return sha256(code.encode("utf-8")).hexdigest()[:20]


def _button(
    text: str, data: str, style: Literal["primary", "success", "danger"] | None = None
) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data, style=style)


def _menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("📋 مدیریت پلن‌ها", "ap:list:0")],
            [_button("➕ پلن جدید", "ap:new", "success")],
            [_button("🦋 هویت و توضیحات بات", "brand:menu")],
        ]
    )


def _list_keyboard(plans: list[Plan], page: int) -> InlineKeyboardMarkup:
    pages = max(1, (len(plans) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, pages - 1)
    visible = plans[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    rows = [
        [
            _button(
                f"{'🟢' if plan.is_active else '⚪️'} {plan.emoji} {plan.title} · {plan.code}",
                f"ap:plan:{_key(plan.code)}",
            )
        ]
        for plan in visible
    ]
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(_button("⬅️ قبلی", f"ap:list:{page - 1}"))
    if page + 1 < pages:
        navigation.append(_button("بعدی ➡️", f"ap:list:{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([_button("➕ پلن جدید", "ap:new", "success")])
    rows.append([_button("↩️ منوی مدیریت", "ap:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _plan_keyboard(plan: Plan) -> InlineKeyboardMarkup:
    next_state = 0 if plan.is_active else 1
    action = "⏸ غیرفعال‌کردن" if plan.is_active else "▶️ فعال‌کردن"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button(
                    action,
                    f"ap:status:{_key(plan.code)}:{next_state}",
                    "danger" if plan.is_active else "success",
                )
            ],
            [_button("✏️ ویرایش پلن", f"ap:edit:{_key(plan.code)}")],
            [_button("↩️ همهٔ پلن‌ها", "ap:list:0")],
        ]
    )


def _plan_text(plan: Plan) -> str:
    price = f"{plan.price_toman:,}".replace(",", "٬")
    state = "🟢 فعال و قابل نمایش به مشتری" if plan.is_active else "⚪️ غیرفعال"
    return (
        f"{RTL}{escape(plan.emoji)} <b>{escape(plan.title)}</b>\n"
        f"{RTL}کد: <code>{escape(plan.code)}</code>\n\n"
        f"{RTL}📦 {plan.traffic_gb} گیگابایت · 🗓 {plan.duration_days} روز\n"
        f"{RTL}💳 {price} تومان\n"
        f"{RTL}وضعیت: {state}"
    )


def _form_prompt(plan: Plan | None = None) -> str:
    if plan is None:
        return (
            f"{RTL}<b>پلن جدید</b>\n"
            f"{RTL}اطلاعات را در ۷ خط بفرستید:\n"
            f"{RTL}کد، عنوان، ایموجی، حجم (گیگابایت)، مدت (روز)، قیمت (ریال)، ترتیب.\n\n"
            "<code>M60\nپلن ۶۰ گیگ\n⚡\n60\n30\n990000\n20</code>\n\n"
            f"{RTL}۹۹۰٬۰۰۰ ریال در بات ۹۹٬۰۰۰ تومان نمایش داده می‌شود.\n"
            f"{RTL}پلن تازه ابتدا غیرفعال می‌ماند. برای لغو /cancel را بفرستید."
        )
    return (
        f"{RTL}<b>ویرایش {escape(plan.title)}</b>\n"
        f"{RTL}کد <code>{escape(plan.code)}</code> ثابت می‌ماند.\n"
        f"{RTL}۶ خط را به ترتیب عنوان، ایموجی، حجم، مدت، قیمت ریالی و ترتیب بفرستید:\n\n"
        f"<code>{escape(plan.title)}\n{escape(plan.emoji)}\n{plan.traffic_gb}\n{plan.duration_days}\n"
        f"{plan.price_rial}\n{plan.sort_order}</code>\n\n"
        f"{RTL}برای لغو /cancel را بفرستید."
    )


def _form_values(text: str, editing: bool) -> tuple[str, str, str, int, int, int, int]:
    lines = [line.strip() for line in text.splitlines()]
    expected = 6 if editing else 7
    if len(lines) != expected or any(not line for line in lines):
        raise PlanValidationError(f"دقیقاً {expected} خط غیرخالی بفرستید.")
    if editing:
        title, emoji, raw_traffic, raw_duration, raw_price, raw_order = lines
        code = ""
    else:
        code, title, emoji, raw_traffic, raw_duration, raw_price, raw_order = lines
    try:
        return (
            code,
            title,
            emoji,
            int(raw_traffic),
            int(raw_duration),
            int(raw_price),
            int(raw_order),
        )
    except ValueError as exc:
        raise PlanValidationError(
            "حجم، مدت، قیمت ریالی و ترتیب نمایش باید عدد صحیح باشند."
        ) from exc


def build_admin_router(service: AdminPlanService) -> Router:
    """Register private-chat admin views; include this router in the dispatcher."""
    router = Router(name="papilio_admin_plans")

    async def authorized(callback: CallbackQuery) -> bool:
        if callback.from_user.id not in service.admin_ids or not isinstance(
            callback.message, Message
        ):
            await callback.answer("دسترسی مجاز نیست.", show_alert=True)
            return False
        if callback.message.chat.type != ChatType.PRIVATE:
            await callback.answer("مدیریت فقط در گفت‌وگوی خصوصی بات در دسترس است.", show_alert=True)
            return False
        return True

    async def show(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup) -> None:
        if isinstance(callback.message, Message):
            await callback.message.edit_text(text, reply_markup=keyboard)

    async def find_plan(callback: CallbackQuery, key: str) -> Plan | None:
        try:
            plans = await service.list_plans(callback.from_user.id)
        except AdminAccessError:
            await callback.answer("دسترسی مجاز نیست.", show_alert=True)
            return None
        matches = [plan for plan in plans if _key(plan.code) == key]
        if len(matches) != 1:
            await callback.answer("پلن پیدا نشد. فهرست را دوباره باز کنید.", show_alert=True)
            return None
        return matches[0]

    @router.message(Command("myid"))
    async def my_id(message: Message) -> None:
        if message.from_user is not None:
            await message.answer(f"{RTL}شناسهٔ تلگرام شما: <code>{message.from_user.id}</code>")

    @router.message(Command("admin"))
    async def admin_menu(message: Message, state: FSMContext) -> None:
        if message.from_user is None or message.from_user.id not in service.admin_ids:
            await message.answer("دسترسی مدیریت مجاز نیست.")
            return
        if message.chat.type != ChatType.PRIVATE:
            await message.answer("برای مدیریت پلن‌ها در گفت‌وگوی خصوصی بات /admin را بفرستید.")
            return
        await state.clear()
        await message.answer(
            f"{RTL}<b>مرکز مدیریت پاپیلیو</b>\n{RTL}پلن‌ها و هویت بات را از اینجا مدیریت کنید.",
            reply_markup=_menu_keyboard(),
        )

    @router.callback_query(F.data == "ap:menu")
    async def menu(callback: CallbackQuery, state: FSMContext) -> None:
        if not await authorized(callback):
            return
        await state.clear()
        await callback.answer()
        await show(
            callback,
            f"{RTL}<b>مرکز مدیریت پاپیلیو</b>\n{RTL}از اینجا پلن‌ها را مدیریت کنید.",
            _menu_keyboard(),
        )

    @router.callback_query(F.data.startswith("ap:list:"))
    async def list_plans(callback: CallbackQuery, state: FSMContext) -> None:
        if not await authorized(callback):
            return
        raw_page = (callback.data or "").removeprefix("ap:list:")
        if not raw_page.isdecimal():
            await callback.answer("درخواست معتبر نیست.", show_alert=True)
            return
        await state.clear()
        plans = await service.list_plans(callback.from_user.id)
        page = min(int(raw_page), max(0, (len(plans) - 1) // PAGE_SIZE))
        await callback.answer()
        body = (
            f"{RTL}<b>پلن‌های پاپیلیو</b>\n"
            f"{RTL}{len(plans)} پلن · صفحهٔ {page + 1}\n\n"
            f"{RTL}🟢 فعال    ⚪️ غیرفعال\n"
            f"{RTL}برای دیدن جزئیات، یک پلن را انتخاب کنید."
            if plans
            else f"{RTL}هنوز پلنی ثبت نشده است."
        )
        await show(callback, body, _list_keyboard(plans, page))

    @router.callback_query(F.data.startswith("ap:plan:"))
    async def plan_detail(callback: CallbackQuery, state: FSMContext) -> None:
        if not await authorized(callback):
            return
        await state.clear()
        key = (callback.data or "").removeprefix("ap:plan:")
        plan = await find_plan(callback, key)
        if plan is None:
            return
        await callback.answer()
        await show(callback, _plan_text(plan), _plan_keyboard(plan))

    @router.callback_query(F.data.startswith("ap:status:"))
    async def change_status(callback: CallbackQuery, state: FSMContext) -> None:
        if not await authorized(callback):
            return
        await state.clear()
        parts = (callback.data or "").split(":")
        if len(parts) != 4 or parts[3] not in {"0", "1"}:
            await callback.answer("درخواست معتبر نیست.", show_alert=True)
            return
        plan = await find_plan(callback, parts[2])
        if plan is None:
            return
        try:
            updated = await service.set_active(callback.from_user.id, plan.code, parts[3] == "1")
        except UnknownPlanError:
            await callback.answer("پلن پیدا نشد. فهرست را دوباره باز کنید.", show_alert=True)
            return
        await callback.answer("وضعیت پلن ثبت شد.")
        await show(
            callback,
            f"{RTL}✅ وضعیت «{escape(updated.title)}» ثبت شد.\n\n{RTL}{_plan_text(updated)}",
            _menu_keyboard(),
        )

    @router.callback_query(F.data == "ap:new")
    async def new_plan(callback: CallbackQuery, state: FSMContext) -> None:
        if not await authorized(callback):
            return
        await state.clear()
        await state.set_state(PlanForm.waiting)
        await state.update_data(editing=False)
        await callback.answer()
        await show(
            callback,
            _form_prompt(),
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [_button("لغو و بازگشت", "ap:menu")],
                ]
            ),
        )

    @router.callback_query(F.data.startswith("ap:edit:"))
    async def edit_plan(callback: CallbackQuery, state: FSMContext) -> None:
        if not await authorized(callback):
            return
        plan = await find_plan(callback, (callback.data or "").removeprefix("ap:edit:"))
        if plan is None:
            return
        await state.clear()
        await state.set_state(PlanForm.waiting)
        await state.update_data(editing=True, code=plan.code)
        await callback.answer()
        await show(
            callback,
            _form_prompt(plan),
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [_button("لغو و بازگشت", "ap:menu")],
                ]
            ),
        )

    @router.message(Command("cancel"))
    async def cancel_form(message: Message, state: FSMContext) -> None:
        if message.from_user is None or message.from_user.id not in service.admin_ids:
            return
        await state.clear()
        await message.answer(
            f"{RTL}فرم لغو شد. به منوی مدیریت برگشتید.", reply_markup=_menu_keyboard()
        )

    @router.message(PlanForm.waiting)
    async def receive_plan(message: Message, state: FSMContext) -> None:
        if message.from_user is None or message.from_user.id not in service.admin_ids:
            await state.clear()
            await message.answer("دسترسی مدیریت مجاز نیست.")
            return
        if message.chat.type != ChatType.PRIVATE:
            await state.clear()
            await message.answer("ویرایش پلن فقط در گفت‌وگوی خصوصی بات انجام می‌شود.")
            return
        data = await state.get_data()
        editing = data.get("editing") is True
        try:
            code, title, emoji, traffic, duration, price, order = _form_values(
                message.text or "", editing
            )
            if editing:
                stored_code = data.get("code")
                if not isinstance(stored_code, str):
                    raise PlanValidationError("فرم منقضی شده است؛ دوباره از منوی مدیریت شروع کنید.")
                code = stored_code
            plan = await service.save_plan(
                message.from_user.id,
                code=code,
                title=title,
                traffic_gb=traffic,
                duration_days=duration,
                price_rial=price,
                sort_order=order,
                emoji=emoji,
                editing=editing,
            )
        except (PlanValidationError, UnknownPlanError) as exc:
            await message.answer(
                f"{RTL}⚠️ {escape(str(exc))}\n{RTL}دوباره بفرستید یا /cancel را بزنید."
            )
            return
        await state.clear()
        await message.answer(
            f"{RTL}✅ پلن ذخیره شد. به منوی مدیریت برگشتید.\n\n{_plan_text(plan)}",
            reply_markup=_menu_keyboard(),
        )

    return router
