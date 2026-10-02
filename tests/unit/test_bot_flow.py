from __future__ import annotations

from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from aiogram import Bot, Dispatcher
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendAnimation, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, MessageEntity, Update, User

from bot.core.config import Settings
from bot.models import Plan, Protocol
from bot.presentation.ui import _key, build_router
from bot.services.subscriptions import SubscriptionService
from tests.unit.test_subscriptions import MemorySubscriptionRepository


class BotFlowTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.repository = MemorySubscriptionRepository()
        self.service = SubscriptionService(self.repository, self.repository)
        self.bot = Bot("123456:TEST_TOKEN")
        self.dispatcher = Dispatcher()
        settings = Settings(None, "mysql+aiomysql://", frozenset({77}), None, None, None)
        self.dispatcher.include_router(build_router(self.service, settings))
        self.transport = patch.object(self.bot.session, "make_request", new_callable=AsyncMock)
        self.send = self.transport.start()
        self.send.return_value = True

    async def asyncTearDown(self) -> None:
        self.transport.stop()
        await self.bot.session.close()

    def message(self, text: str, owner: int = 77, chat_type: str = "private") -> Message:
        return Message(
            message_id=1,
            date=datetime.now(UTC),
            text=text,
            chat=Chat(id=owner, type=chat_type),
            from_user=User(id=owner, is_bot=False, first_name="<پویا>"),
            entities=[MessageEntity(type="bot_command", offset=0, length=len(text))],
        )

    async def command(self, text: str, owner: int = 77, chat_type: str = "private") -> None:
        await self.dispatcher.feed_update(
            self.bot, Update(update_id=1, message=self.message(text, owner, chat_type))
        )

    async def callback(self, data: str, owner: int = 77) -> None:
        await self.dispatcher.feed_update(
            self.bot,
            Update(
                update_id=2,
                callback_query=CallbackQuery(
                    id="test",
                    from_user=User(id=owner, is_bot=False, first_name="تست"),
                    chat_instance="test",
                    message=self.message("صفحه", owner),
                    data=data,
                ),
            ),
        )

    async def test_start_plans_and_vmess_order_keep_server_side_price_and_quota(self) -> None:
        await self.repository.save(Plan("dynamic", "پلن <آزمایش>", 17, 21, 123_450))
        await self.command("/start")
        self.assertIn(77, self.repository.users)
        animation = self.send.await_args_list[-1].args[1]
        self.assertIsInstance(animation, SendAnimation)
        self.assertIn("&lt;پویا&gt;", animation.caption)
        await self.command("/plans")
        listing = self.send.await_args_list[-1].args[1]
        self.assertIsInstance(listing, SendMessage)
        self.assertIn("12٬345 تومان", listing.text)
        self.assertIn("&lt;آزمایش&gt;", listing.text)
        await self.callback("plan:" + _key("dynamic"))
        self.assertIsInstance(self.send.await_args_list[-1].args[1], EditMessageText)
        await self.callback("order:" + _key("dynamic") + ":vmess")
        self.assertEqual(len(self.repository.records), 1)
        order = self.repository.records[0]
        self.assertEqual(order.price_rial, 123_450)
        self.assertEqual(order.traffic_limit_bytes, 17 * 1024**3)
        self.assertEqual(order.protocol, Protocol.VMESS)
        self.assertIn("فعلاً مبلغی واریز نکن", self.send.await_args_list[-1].args[1].text)

    async def test_public_purchase_button_orders_both_links_with_one_quota(self) -> None:
        await self.repository.save(Plan("both", "دو اتصال", 30, 30, 590_000))
        await self.callback("order:" + _key("both") + ":both")
        order = self.repository.records[0]
        self.assertEqual(order.protocol, Protocol.BOTH)
        self.assertEqual(order.duration_days, 30)
        self.assertEqual(order.traffic_limit_bytes, 30 * 1024**3)
        self.assertIn("VLESS + VMess", self.send.await_args_list[-1].args[1].text)

    async def test_group_command_does_not_register_or_reply(self) -> None:
        await self.command("/start", chat_type="group")
        self.send.assert_not_awaited()
        self.assertEqual(self.repository.users, {})

    async def test_order_from_plans_without_start_registers_customer(self) -> None:
        await self.repository.save(Plan("fresh", "تازه", 9, 30, 100))
        await self.command("/plans", owner=88)
        self.assertNotIn(88, self.repository.users)
        await self.callback("order:" + _key("fresh") + ":vmess", owner=88)
        self.assertIn(88, self.repository.users)
        self.assertEqual(self.repository.records[0].telegram_id, 88)

    async def test_bad_page_and_unavailable_plan_do_not_create_orders(self) -> None:
        await self.callback("plans:invalid")
        self.assertIsInstance(self.send.await_args_list[-1].args[1], AnswerCallbackQuery)
        await self.repository.save(Plan("hidden", "غیرفعال", 3, 30, 10, False))
        await self.callback("order:" + _key("hidden") + ":vmess")
        self.assertEqual(self.repository.records, [])

    async def test_subscriptions_do_not_leak_between_users(self) -> None:
        await self.repository.save(Plan("owned", "فقط مالک", 7, 10, 100))
        order = await self.service.create_order(77, "owned", Protocol.VMESS)
        await self.command("/myservices", owner=88)
        listing = self.send.await_args_list[-1].args[1]
        self.assertNotIn(order.id[:8], listing.text)
        self.assertNotIn("فقط مالک", listing.text)

    async def test_payment_return_cannot_read_another_customers_order(self) -> None:
        await self.repository.save(Plan("owned", "فقط مالک", 7, 10, 100))
        order = await self.service.create_order(77, "owned", Protocol.BOTH)
        await self.command("/start paid_" + order.id, owner=88)
        response = self.send.await_args_list[-1].args[1]
        self.assertIsInstance(response, SendMessage)
        self.assertIn("برای حساب تو پیدا نشد", response.text)
        self.assertNotIn(order.id, response.text)

    async def test_payment_return_does_not_trust_paid_parameter(self) -> None:
        await self.repository.save(Plan("owned", "فقط مالک", 7, 10, 100))
        order = await self.service.create_order(77, "owned", Protocol.BOTH)
        await self.command("/start paid_" + order.id)
        response = self.send.await_args_list[-1].args[1]
        self.assertIsInstance(response, SendMessage)
        self.assertIn("هنوز تأیید پرداخت ثبت نشده", response.text)
