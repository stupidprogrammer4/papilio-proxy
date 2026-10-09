"""Trial presentation and retries with controlled API/Telegram HTTP."""

import json
from unittest import IsolatedAsyncioTestCase

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.types import Update
from aiohttp import web

from papilio_telegram.api import BotApi
from papilio_telegram.config import BotApiLimits
from papilio_telegram.handlers import register


class TrialConsumerTest(IsolatedAsyncioTestCase):
    async def test_trial_reason_cooldown_status_and_durable_retry(self):
        calls, telegram_calls = [], []
        availability = "cooldown"
        claim_count = 0
        renewal_mode = "self"

        async def api_handler(request):
            nonlocal claim_count
            body = await request.json()
            self.assertEqual(body["telegram_id"], 61)
            self.assertEqual(body["display_name"], "Customer")
            self.assertEqual(
                request.headers["X-Papilio-Bot-Key"], "controlled-api-key"
            )
            calls.append((request.path, body))
            if request.path == "/v1/bot/home":
                data = {
                    "display_name": "Customer",
                    "brand_title": "Private account",
                    "balance_rial": 101,
                }
            elif request.path.endswith("/availability"):
                data = {
                    "policy": {
                        "enabled": True,
                        "plan_id": 42,
                        "eligibility": "any_customer",
                        "concurrent_mode": "reject_active",
                        "max_claims_per_customer": 3,
                        "cooldown_seconds": 120,
                        "quota_bytes": 536870912,
                        "duration_days": 2,
                    },
                    "capacity_valid": True,
                    "eligible": availability == "eligible",
                    "reason": None
                    if availability == "eligible"
                    else "trial_cooldown",
                    "claims": 1,
                    "next_claim_at": None
                    if availability == "eligible"
                    else "2026-10-08T11:30:00+03:30",
                }
                if availability == "malformed":
                    data["next_claim_at"] = "2026-10-08T11:30:00"
            elif request.path.endswith("/renewal-eligibility"):
                data = {
                    "subscription_id": 91,
                    "renewal_generation": 0,
                    "checked_at": "2026-10-08T08:00:00Z",
                    "auto_renew": True,
                    "quote_available": True,
                    "eligible": True,
                    "reason_code": None,
                    "renewal_due": False,
                    "auto_renew_authorized": True,
                    "payer_kind": "self"
                    if renewal_mode == "self"
                    else "other",
                    "wallet_funded": True if renewal_mode == "self" else None,
                    "wallet_balance_rial": 101
                    if renewal_mode == "self"
                    else None,
                    "renewal_price_rial": 101,
                    "wallet_shortfall_rial": 0
                    if renewal_mode == "self"
                    else None,
                }
                if renewal_mode == "malformed":
                    data["wallet_balance_rial"] = 987654321
            elif request.path.endswith("/delivery"):
                data = {
                    "subscription_id": 91,
                    "status": "active",
                    "auto_renew": False,
                    "entitlement_kind": "trial",
                    "portal_url": None,
                    "feed_url": None,
                    "can_rotate_link": False,
                }
            else:
                claim_count += 1
                if claim_count == 1:
                    return web.json_response(
                        {"error": {"message_code": "network"}}, status=503
                    )
                data = {
                    "id": 91,
                    "customer_id": 31,
                    "status": "pending_provision"
                    if claim_count == 2
                    else "active",
                    "entitlement_kind": "trial",
                    "auto_renew": False,
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
        application.router.add_post("/v1/bot/{tail:.*}", api_handler)
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
        bot = Bot(
            "123456:controlled_test_token_abcdefghijklmnopqrstuvwxyz",
            session=AiohttpSession(api=TelegramAPIServer.from_base(origin)),
        )
        dispatcher = Dispatcher(disable_fsm=True)
        dispatcher.include_router(register(api))

        async def feed(
            identifier,
            data,
            accessible=True,
            chat_id=61,
            chat_type="private",
            message_date=1,
        ):
            callback = {
                "id": str(identifier),
                "from": {"id": 61, "is_bot": False, "first_name": "Customer"},
                "chat_instance": "controlled",
                "data": data,
            }
            if accessible:
                callback["message"] = {
                    "message_id": 77,
                    "date": message_date,
                    "chat": {"id": chat_id, "type": chat_type},
                }
            else:
                callback["inline_message_id"] = "controlled-inline-message"
            await dispatcher.feed_update(
                bot,
                Update.model_validate(
                    {"update_id": identifier, "callback_query": callback}
                ),
            )

        async def start(identifier, chat_id, chat_type):
            update = Update.model_validate(
                {
                    "update_id": identifier,
                    "message": {
                        "message_id": identifier,
                        "date": 1,
                        "from": {
                            "id": 61,
                            "is_bot": False,
                            "first_name": "Customer",
                        },
                        "chat": {"id": chat_id, "type": chat_type},
                        "text": "/start",
                    },
                }
            )
            await dispatcher.feed_update(bot, update)

        try:
            await start(10, -100, "group")
            self.assertEqual(calls, [])
            self.assertIn("گفت‌وگوی خصوصی", telegram_calls[-1][1]["text"])
            await feed(11, "account", chat_id=-100, chat_type="supergroup")
            await feed(12, "trial_claim", chat_id=-100, chat_type="supergroup")
            await feed(13, "service:91", chat_id=-100, chat_type="supergroup")
            await start(14, -101, "channel")
            await feed(15, "account", chat_id=62)
            await feed(17, "account", message_date=0)
            self.assertEqual(calls, [])
            self.assertNotIn("https://", str(telegram_calls))
            await start(16, 61, "private")
            self.assertEqual(calls[-1][0], "/v1/bot/home")
            self.assertIn("Private account", telegram_calls[-1][1]["text"])
            await feed(1, "trial")
            message = telegram_calls[-2][1]
            self.assertIn("۰.۵۰ گیبی‌بایت", message["text"])
            self.assertIn("فاصلهٔ لازم", message["text"])
            self.assertIn("۲۰۲۶-۱۰-۰۸ ۰۸:۰۰ UTC", message["text"])
            self.assertNotIn("trial_claim", message["reply_markup"])
            availability = "eligible"
            await feed(2, "trial")
            keyboard = json.loads(telegram_calls[-2][1]["reply_markup"])
            self.assertEqual(
                keyboard["inline_keyboard"][0][0]["callback_data"],
                "trial_claim",
            )
            await feed(3, "trial_claim")
            self.assertIn("همان دکمه", telegram_calls[-2][1]["text"])
            await feed(4, "trial_claim")
            self.assertIn("منتظر آماده‌سازی", telegram_calls[-2][1]["text"])
            self.assertIn("service:91", telegram_calls[-2][1]["reply_markup"])
            await feed(5, "trial_claim")
            self.assertIn("وضعیت فعلی: فعال", telegram_calls[-2][1]["text"])
            claims = [body for path, body in calls if path == "/v1/bot/trials"]
            self.assertEqual(claims[0], claims[1])
            self.assertEqual(claims[1], claims[2])
            self.assertEqual(claims[0]["request_key"], "telegram-trial:77")
            await feed(6, "service:91")
            self.assertEqual(calls[-1][0], "/v1/bot/subscriptions/91/delivery")
            self.assertIn(
                "renewal-status:91", telegram_calls[-2][1]["reply_markup"]
            )
            await feed(20, "renewal-status:91")
            self.assertIn("کیف پول من", telegram_calls[-2][1]["text"])
            self.assertIn("۱۰٫۱ تومان", telegram_calls[-2][1]["text"])
            self.assertIn(
                "به معنی انجام تمدید نیست", telegram_calls[-2][1]["text"]
            )
            renewal_mode = "other"
            await feed(21, "renewal-status:91")
            self.assertIn("خصوصی", telegram_calls[-2][1]["text"])
            self.assertNotIn("کیف پول من", telegram_calls[-2][1]["text"])
            renewal_mode = "malformed"
            await feed(22, "renewal-status:91")
            self.assertNotIn("987654321", telegram_calls[-2][1]["text"])
            self.assertNotIn("reply_markup", telegram_calls[-2][1])
            before = len(calls)
            await feed(7, "trial_claim", accessible=False)
            self.assertEqual(len(calls), before)
            self.assertEqual(telegram_calls[-1][1]["show_alert"], "true")
            availability = "malformed"
            await feed(8, "trial")
            self.assertNotIn("reply_markup", telegram_calls[-2][1])
        finally:
            await api.close()
            await bot.session.close()
            await runner.cleanup()
