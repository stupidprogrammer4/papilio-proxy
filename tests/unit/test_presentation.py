from __future__ import annotations

from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from aiogram.types import CallbackQuery, Chat, Message, PhotoSize, User

from bot.core.config import Settings
from bot.presentation.ui import (
    BANNER_PATH,
    LOGO_PATH,
    PAGE_SIZE,
    _home_keyboard,
    _home_text,
    _plan_card,
    _plans_keyboard,
    _plans_text,
    _protocol_keyboard,
    _show_view,
    _show_welcome,
    _subscription_card,
    build_router,
)
from bot.services.subscriptions import Plan, Protocol, Subscription, SubscriptionStatus


class PresentationTests(TestCase):
    def test_brand_assets_are_available(self) -> None:
        self.assertTrue(BANNER_PATH.is_file())
        self.assertTrue(LOGO_PATH.is_file())

    def test_dynamic_plan_uses_rial_storage_and_toman_display(self) -> None:
        plan = Plan("sample", "پلن آزمایشی", 42, 30, 1_234_560)
        self.assertEqual(plan.price_rial, 1_234_560)
        self.assertEqual(plan.price_toman, 123_456)

    def test_navigation_has_customer_actions(self) -> None:
        home_labels = [button.text for row in _home_keyboard().inline_keyboard for button in row]
        plan_labels = [
            button.text
            for row in _plans_keyboard([Plan("sample", "پلن", 1, 1, 10)]).inline_keyboard
            for button in row
        ]
        self.assertIn("مشاهدهٔ پلن‌ها", home_labels)
        self.assertIn("دربارهٔ پاپیلیو", home_labels)
        self.assertEqual(len(plan_labels), 2)

    def test_user_and_admin_text_is_html_escaped(self) -> None:
        plan = Plan("sample", "<b>پلن & تست</b>", 42, 21, 1_234_560)
        self.assertIn("&lt;Ali &amp; Sara&gt;", _home_text("<Ali & Sara>"))
        card = _plan_card(plan)
        self.assertIn("&lt;b&gt;پلن &amp; تست&lt;/b&gt;", card)
        self.assertIn("123٬456 تومان", card)
        self.assertIn("21 روز", card)

    def test_long_plan_code_fits_all_callback_payloads(self) -> None:
        plan = Plan("x" * 64, "پلن", 1, 30, 590_000)
        for keyboard in (_plans_keyboard([plan]), _protocol_keyboard(plan.code)):
            for row in keyboard.inline_keyboard:
                for button in row:
                    if button.callback_data:
                        self.assertLessEqual(len(button.callback_data.encode("utf-8")), 64)

    def test_plans_are_paginated_and_use_actual_duration(self) -> None:
        plans = [Plan(f"p{i}", f"پلن {i}", 10 + i, i + 1, 100_000) for i in range(8)]
        text = _plans_text(plans, 1)
        labels = [
            button.text for row in _plans_keyboard(plans, 1).inline_keyboard for button in row
        ]
        self.assertIn("پلن 6", text)
        self.assertNotIn("پلن 0", text)
        self.assertIn("7 روز", text)
        self.assertEqual(PAGE_SIZE, 6)
        self.assertIn("⬅️ قبلی", labels)
        self.assertNotIn("بعدی ➡️", labels)

    def test_pending_request_is_not_described_as_active(self) -> None:
        plan = Plan("sample", "پلن", 42, 30, 1_234_560)
        record = Subscription(
            id="12345678-0000",
            telegram_id=1,
            plan_code=plan.code,
            protocol=Protocol.VLESS,
            status=SubscriptionStatus.PENDING_PAYMENT,
            traffic_limit_bytes=plan.traffic_bytes,
            traffic_used_bytes=0,
            expires_at=None,
            created_at=datetime.now(UTC),
            price_rial=plan.price_rial,
        )
        text = _subscription_card(record, plan)
        self.assertIn("پرداخت تأیید نشده", text)
        self.assertNotIn("فعال", text)
        self.assertIn("123٬456 تومان", text)

    def test_public_commands_have_handlers(self) -> None:
        settings = Settings(None, "mysql+aiomysql://", frozenset(), None, None, None)
        router = build_router(AsyncMock(), settings)
        commands = {
            command
            for handler in router.message.handlers
            for wrapped_filter in handler.filters or ()
            for command in (getattr(wrapped_filter.callback, "commands", None) or ())
        }
        self.assertTrue({"start", "plans", "myservices", "help"} <= commands)


class PhotoNavigationTests(IsolatedAsyncioTestCase):
    async def test_start_sends_one_banner_with_dashboard_keyboard(self) -> None:
        message = Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=Chat(id=1, type="private"),
        )
        with (
            patch.object(Message, "answer_photo", new_callable=AsyncMock) as answer_photo,
            patch.object(Message, "answer", new_callable=AsyncMock) as answer,
        ):
            await _show_welcome(message, "پویا")
        answer_photo.assert_awaited_once()
        call = answer_photo.await_args
        assert call is not None
        self.assertIn("پیش‌نمایش", call.kwargs["caption"])
        self.assertIsNotNone(call.kwargs["reply_markup"])
        answer.assert_not_awaited()

    async def test_photo_callback_opens_text_view_without_editing_caption(self) -> None:
        message = Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=Chat(id=1, type="private"),
            photo=[PhotoSize(file_id="photo", file_unique_id="unique", width=1, height=1)],
        )
        callback = CallbackQuery(
            id="query",
            from_user=User(id=1, is_bot=False, first_name="پویا"),
            chat_instance="instance",
            message=message,
            data="home",
        )
        with (
            patch.object(Message, "edit_reply_markup", new_callable=AsyncMock) as clear_keyboard,
            patch.object(Message, "answer", new_callable=AsyncMock) as answer,
            patch.object(Message, "edit_text", new_callable=AsyncMock) as edit_text,
        ):
            await _show_view(callback, "خانه", _home_keyboard())
        clear_keyboard.assert_awaited_once_with(reply_markup=None)
        answer.assert_awaited_once()
        edit_text.assert_not_awaited()

    async def test_photo_callback_can_return_to_dashboard_in_caption(self) -> None:
        message = Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=Chat(id=1, type="private"),
            photo=[PhotoSize(file_id="photo", file_unique_id="unique", width=1, height=1)],
        )
        callback = CallbackQuery(
            id="query",
            from_user=User(id=1, is_bot=False, first_name="پویا"),
            chat_instance="instance",
            message=message,
            data="home",
        )
        with (
            patch.object(Message, "edit_caption", new_callable=AsyncMock) as edit_caption,
            patch.object(Message, "answer", new_callable=AsyncMock) as answer,
        ):
            await _show_view(callback, _home_text("پویا"), _home_keyboard(), caption_ok=True)
        edit_caption.assert_awaited_once()
        answer.assert_not_awaited()
