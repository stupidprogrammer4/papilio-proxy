from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.models.branding import BotBranding, BrandingValidationError
from bot.presentation.profile import sync_bot_photo, sync_bot_profile
from bot.services.branding import BrandingField, BrandingService

FIELD_LABELS: dict[BrandingField, str] = {
    "name": "نام بات",
    "short_description": "توضیح کوتاه",
    "description": "توضیح کامل",
}


def _field(value: object) -> BrandingField | None:
    if value == "name":
        return "name"
    if value == "short_description":
        return "short_description"
    if value == "description":
        return "description"
    return None


class BrandingForm(StatesGroup):
    waiting = State()


def _menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ نام بات", callback_data="brand:edit:name")],
            [
                InlineKeyboardButton(
                    text="✏️ توضیح کوتاه", callback_data="brand:edit:short_description"
                )
            ],
            [InlineKeyboardButton(text="✏️ توضیح کامل", callback_data="brand:edit:description")],
            [InlineKeyboardButton(text="🔄 همگام‌سازی متن و فرمان‌ها", callback_data="brand:sync")],
            [
                InlineKeyboardButton(
                    text="🖼 تنظیم لوگو به‌عنوان عکس پروفایل", callback_data="brand:photo"
                )
            ],
        ]
    )


def _branding_text(branding: BotBranding) -> str:
    return (
        "🦋 <b>هویت بات پاپیلیو</b>\n\n"
        f"<b>نام:</b> {escape(branding.name)}\n"
        f"<b>توضیح کوتاه:</b> {escape(branding.short_description)}\n\n"
        f"<b>توضیح کامل:</b>\n{escape(branding.description)}\n\n"
        "تغییرات در MySQL ذخیره می‌شوند و متن پروفایل تلگرام هم همگام می‌شود. "
        "عکس صفحهٔ توضیحاتِ BotFather جدا از عکس پروفایل است."
    )


def build_branding_router(service: BrandingService, admin_ids: frozenset[int]) -> Router:
    router = Router(name="papilio_admin_branding")

    async def authorized_callback(callback: CallbackQuery) -> bool:
        if (
            callback.from_user.id not in admin_ids
            or not isinstance(callback.message, Message)
            or callback.message.chat.type != ChatType.PRIVATE
        ):
            await callback.answer("دسترسی مجاز نیست.", show_alert=True)
            return False
        return True

    @router.message(Command("branding"))
    async def branding_menu(message: Message, state: FSMContext) -> None:
        if (
            message.from_user is None
            or message.from_user.id not in admin_ids
            or message.chat.type != ChatType.PRIVATE
        ):
            await message.answer("مدیریت پروفایل فقط برای ادمین و در گفت‌وگوی خصوصی فعال است.")
            return
        await state.clear()
        await message.answer(_branding_text(await service.get()), reply_markup=_menu())

    @router.callback_query(F.data == "brand:menu")
    async def back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
        if not await authorized_callback(callback):
            return
        await state.clear()
        await callback.answer()
        if isinstance(callback.message, Message):
            await callback.message.edit_text(
                _branding_text(await service.get()), reply_markup=_menu()
            )

    @router.callback_query(F.data.startswith("brand:edit:"))
    async def edit_field(callback: CallbackQuery, state: FSMContext) -> None:
        if not await authorized_callback(callback):
            return
        raw_field = (callback.data or "").removeprefix("brand:edit:")
        field = _field(raw_field)
        if field is None:
            await callback.answer("فیلد معتبر نیست.", show_alert=True)
            return
        await state.clear()
        await state.set_state(BrandingForm.waiting)
        await state.update_data(field=field)
        await callback.answer()
        if isinstance(callback.message, Message):
            await callback.message.edit_text(
                f"✏️ متن جدید «{FIELD_LABELS[field]}» را بفرست. برای لغو، دکمهٔ زیر را بزن.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="↩️ لغو", callback_data="brand:menu")]
                    ]
                ),
            )

    @router.message(BrandingForm.waiting)
    async def save_field(message: Message, state: FSMContext) -> None:
        if (
            message.from_user is None
            or message.from_user.id not in admin_ids
            or message.chat.type != ChatType.PRIVATE
        ):
            await state.clear()
            await message.answer("دسترسی مجاز نیست.")
            return
        data = await state.get_data()
        field = _field(data.get("field"))
        if field is None:
            await state.clear()
            await message.answer("فرم منقضی شده؛ دوباره /branding را بزن.")
            return
        try:
            branding = await service.update(field, message.text or "")
        except BrandingValidationError as exc:
            await message.answer(f"⚠️ {escape(str(exc))}\nدوباره بفرست یا /cancel را بزن.")
            return
        await state.clear()
        if message.bot is not None:
            try:
                await sync_bot_profile(message.bot, branding)
            except TelegramAPIError:
                await message.answer(
                    "✅ در دیتابیس ذخیره شد، اما همگام‌سازی تلگرام ناموفق بود. "
                    "از /branding دکمهٔ همگام‌سازی را بزن."
                )
                return
        await message.answer("✅ پروفایل ذخیره و همگام شد.", reply_markup=_menu())

    @router.callback_query(F.data == "brand:sync")
    async def sync_text(callback: CallbackQuery) -> None:
        if not await authorized_callback(callback):
            return
        if callback.bot is None:
            await callback.answer("بات در دسترس نیست.", show_alert=True)
            return
        try:
            await sync_bot_profile(callback.bot, await service.get())
        except TelegramAPIError:
            await callback.answer("همگام‌سازی ناموفق بود؛ بعداً دوباره تلاش کن.", show_alert=True)
            return
        await callback.answer("متن و فرمان‌های پروفایل همگام شدند.", show_alert=True)

    @router.callback_query(F.data == "brand:photo")
    async def sync_photo(callback: CallbackQuery) -> None:
        if not await authorized_callback(callback):
            return
        if callback.bot is None:
            await callback.answer("بات در دسترس نیست.", show_alert=True)
            return
        try:
            await sync_bot_photo(callback.bot)
        except (TelegramAPIError, FileNotFoundError):
            await callback.answer("تنظیم عکس پروفایل ناموفق بود.", show_alert=True)
            return
        await callback.answer("لوگوی موجود به‌عنوان عکس پروفایل ثبت شد.", show_alert=True)

    return router
