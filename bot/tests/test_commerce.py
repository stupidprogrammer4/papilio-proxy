"""Actual aiogram consumer against controlled API and Telegram HTTP servers."""

import json
from unittest import IsolatedAsyncioTestCase

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.types import Update
from aiohttp import web

from papilio_telegram.api import BotApi
from papilio_telegram.commerce import BotPresentation
from papilio_telegram.config import BotApiLimits
from papilio_telegram.handlers import register


class CommerceConsumerTest(IsolatedAsyncioTestCase):
    async def test_loyalty_quote_failure_and_purchase_retry(self) -> None:
        calls, telegram_calls = [], []
        quota = 1024**3
        quote_fail = False
        zero_quote = False
        malformed_quote = False
        purchase_fail = True
        malformed_invoice = False
        missing_invoice = False
        tier = {
            "id": 7,
            "code": "silver",
            "title": "Silver",
            "minimum_bytes": 200 * quota,
            "discount_bps": 500,
        }
        next_tier = {
            **tier,
            "id": 8,
            "code": "gold",
            "title": "Gold",
            "minimum_bytes": 700 * quota,
        }

        async def api_handler(request):
            nonlocal purchase_fail
            if request.path == "/v1/bot/presentation":
                return web.json_response(
                    {"data": BotPresentation().model_dump(mode="json")}
                )
            body = await request.json()
            self.assertEqual(
                request.headers.get("X-Papilio-Bot-Key"), "controlled-api-key"
            )
            self.assertEqual(body["telegram_id"], 61)
            calls.append((request.path, body))
            if request.path == "/v1/bot/topups":
                data = {"id": 5, "amount_rial": 1051234, "status": "pending"}
            elif request.path == "/v1/bot/topups/5/payment-instruction":
                data = {
                    "destination_id": 3,
                    "title": "Invoice bank",
                    "kind": "card",
                    "account": "1111222233334444",
                    "recipient": "Customer",
                    "bank_name": "Bank",
                    "instructions": None,
                    "topup_id": 5,
                    "requested_amount_rial": 1050000,
                    "payable_amount_rial": 1051234,
                    "payment_identifier_mode": "rial_suffix4",
                    "payment_identifier_code4": "1234",
                }
                if malformed_invoice:
                    data["payable_amount_rial"] = 1051235
                if missing_invoice:
                    data = None
            elif request.path == "/v1/bot/home":
                data = {"payment_instructions": "DO NOT SHOW STALE ACCOUNT"}
            elif request.path == "/v1/bot/loyalty":
                data = {
                    "customer_id": 31,
                    "purchased_bytes": 250 * quota,
                    "purchase_count": 4,
                    "lifetime_purchase_count": 5,
                    "tier": tier,
                    "next_tier": next_tier,
                }
            elif request.path.endswith("/quote"):
                if quote_fail:
                    return web.json_response(
                        {"error": {"message_code": "network"}}, status=503
                    )
                data = {
                    "customer_id": 31,
                    "plan_id": 42,
                    "base_price_rial": 111,
                    "price_rial": -1
                    if malformed_quote
                    else 0
                    if zero_quote
                    else 101,
                    "discount_rial": 111 if zero_quote else 10,
                    "renewal_price_rial": 105,
                    "tier_code": "silver",
                    "tier_discount_bps": 500,
                    "first_purchase_discount_bps": 1000,
                    "policy_revision": 3,
                }
            elif request.path == "/v1/bot/purchase":
                if purchase_fail:
                    purchase_fail = False
                    return web.json_response(
                        {"error": {"message_code": "network"}}, status=503
                    )
                data = {"id": 91}
            else:
                data = {
                    "id": 42,
                    "title": "Selected plan",
                    "price_rial": 111,
                    "quota_bytes": 5 * quota,
                    "duration_days": None,
                }
            return web.json_response({"success": True, "data": data})

        async def telegram_handler(request):
            data = dict(await request.post())
            method = request.match_info["method"]
            telegram_calls.append((method, data))
            result = (
                True
                if method == "answerCallbackQuery"
                else {
                    "message_id": len(telegram_calls),
                    "date": 1,
                    "chat": {"id": 61, "type": "private"},
                    "text": data["text"],
                }
            )
            return web.json_response({"ok": True, "result": result})

        application = web.Application(client_max_size=65536)
        application.router.add_route("*", "/v1/bot/{tail:.*}", api_handler)
        application.router.add_post("/bot{token}/{method}", telegram_handler)
        runner = web.AppRunner(application, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        origin = f"http://127.0.0.1:{runner.addresses[0][1]}"
        api = BotApi(
            origin,
            "controlled-api-key",
            5,
            BotApiLimits(65536, 4, 4096, 10, 10),
        )
        session = AiohttpSession(api=TelegramAPIServer.from_base(origin))
        bot = Bot(
            "123456:controlled_test_token_abcdefghijklmnopqrstuvwxyz",
            session=session,
        )
        dispatcher = Dispatcher(disable_fsm=True)
        dispatcher.include_router(register(api))

        async def feed(identifier, data, message_id=77):
            update = Update.model_validate(
                {
                    "update_id": identifier,
                    "callback_query": {
                        "id": str(identifier),
                        "from": {
                            "id": 61,
                            "is_bot": False,
                            "first_name": "Customer",
                        },
                        "chat_instance": "controlled",
                        "data": data,
                        "message": {
                            "message_id": message_id,
                            "date": 1,
                            "chat": {"id": 61, "type": "private"},
                        },
                    },
                }
            )
            await dispatcher.feed_update(bot, update)

        try:
            await feed(100, "topup:1050000")
            invoice = telegram_calls[-2][1]
            self.assertEqual(invoice["parse_mode"], "HTML")
            self.assertIn("<code>1051234</code>", invoice["text"])
            self.assertNotIn("DO NOT SHOW STALE ACCOUNT", invoice["text"])
            copies = json.loads(invoice["reply_markup"])["inline_keyboard"]
            self.assertEqual(
                copies[0][0]["copy_text"]["text"], "1111222233334444"
            )
            self.assertEqual(copies[1][0]["copy_text"]["text"], "1051234")
            malformed_invoice = True
            await feed(101, "topup:1050000")
            self.assertNotIn("<code>", telegram_calls[-2][1]["text"])
            malformed_invoice = False
            missing_invoice = True
            await feed(102, "topup:1050000")
            self.assertIn("قبل از واریز", telegram_calls[-2][1]["text"])
            self.assertNotIn("1051234", telegram_calls[-2][1]["text"])
            missing_invoice = False
            await feed(1, "loyalty")
            loyalty = telegram_calls[-2][1]["text"]
            self.assertIn("Silver", loyalty)
            self.assertIn("Gold", loyalty)
            self.assertIn("۴۵۰.۰۰", loyalty)
            quote_fail = True
            await feed(2, "plan:42")
            self.assertNotIn("reply_markup", telegram_calls[-2][1])
            quote_fail = False
            await feed(3, "plan:42")
            message = telegram_calls[-2][1]
            self.assertIn("۱۰٫۱ تومان", message["text"])
            self.assertIn("۱۰٫۵ تومان", message["text"])
            self.assertIn("بدون مدت", message["text"])
            keyboard = json.loads(message["reply_markup"])
            self.assertEqual(
                keyboard["inline_keyboard"][0][0]["callback_data"],
                "buy:42:0:101",
            )
            await feed(4, "buy:42:0:101")
            await feed(5, "buy:42:0:101")
            purchases = [
                body for path, body in calls if path == "/v1/bot/purchase"
            ]
            self.assertEqual(purchases[0], purchases[1])
            self.assertEqual(purchases[0]["expected_price_rial"], 101)
            self.assertEqual(purchases[0]["purchase_key"], "tg:61:77:42:0")
            zero_quote = True
            await feed(6, "plan:42", 78)
            free_keyboard = json.loads(telegram_calls[-2][1]["reply_markup"])
            self.assertEqual(
                free_keyboard["inline_keyboard"][0][0]["callback_data"],
                "buy:42:0:0",
            )
            await feed(7, "buy:42:0:0", 78)
            self.assertEqual(calls[-1][1]["expected_price_rial"], 0)
            self.assertEqual(calls[-1][1]["purchase_key"], "tg:61:78:42:0")
            malformed_quote = True
            await feed(8, "plan:42", 79)
            self.assertNotIn("reply_markup", telegram_calls[-2][1])

        finally:
            await api.close()
            await bot.session.close()
            await runner.cleanup()
