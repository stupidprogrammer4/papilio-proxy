"""Actual delivery and aiogram callbacks against controlled backend HTTP."""

import json
from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.types import Update
from aiohttp import ClientSession, web

from papilio_telegram.api import BotApi
from papilio_telegram.checkout import CheckoutDraftLimits
from papilio_telegram.config import BotApiLimits, BotSettings
from papilio_telegram.delivery import register_delivery
from papilio_telegram.handlers import register


class CheckoutNoticeConsumerTest(IsolatedAsyncioTestCase):
    async def test_checkout_action_current_owner_private_guard_and_legacy(
        self,
    ):
        calls, sent = [], []
        status_missing = False
        action = {"kind": "checkout", "checkout_id": 12}
        intent = {
            "id": 12,
            "customer_id": 7,
            "plan_id": 42,
            "revision": 9,
            "state": "cancelled",
            "funding_mode": "approved_topup",
            "delivery_mode": "manual_profiles",
            "price_rial": 120005,
            "offer_sha256": "a" * 64,
            "auto_renew": False,
            "expires_at": "2026-10-09T00:00:00Z",
            "changed_offer_action": "require_confirmation",
            "topup_id": 4,
            "subscription_id": None,
            "reason_code": None,
        }

        async def backend(request):
            body = await request.json()
            calls.append((request.path, body))
            if request.path.endswith("/authorize"):
                data = {
                    "allowed": True,
                    "telegram_id": 61,
                    "text": "Captured notice: conditions changed",
                    "lease_until": (
                        datetime.now(UTC) + timedelta(minutes=5)
                    ).isoformat(),
                }
                if action is not None:
                    data["action"] = action
            elif request.path == "/v1/bot/checkouts/12/status":
                self.assertEqual(body["telegram_id"], 61)
                if status_missing:
                    return web.json_response(
                        {"error": {"message_code": "checkout_not_found"}},
                        status=404,
                    )
                data = intent
            else:
                self.fail("Unexpected business endpoint " + request.path)
            return web.json_response({"success": True, "data": data})

        async def telegram(request):
            fields = dict(await request.post())
            method = request.match_info["method"]
            sent.append((method, fields))
            result = (
                True
                if method == "answerCallbackQuery"
                else {
                    "message_id": len(sent),
                    "date": 1,
                    "chat": {"id": 61, "type": "private"},
                    "text": fields["text"],
                }
            )
            return web.json_response({"ok": True, "result": result})

        controlled = web.Application()
        controlled.router.add_post("/v1/bot/{tail:.*}", backend)
        controlled.router.add_post("/bot{token}/{method}", telegram)
        control_runner = web.AppRunner(controlled, access_log=None)
        await control_runner.setup()
        site = web.TCPSite(control_runner, "127.0.0.1", 0)
        await site.start()
        origin = f"http://127.0.0.1:{control_runner.addresses[0][1]}"
        limits = BotApiLimits(65536, 4, 4096, 10, 10)
        checkout_limits = CheckoutDraftLimits(20, 60, 5)
        api = BotApi(origin, "controlled-key", 5, limits)
        bot = Bot(
            "123456:controlled_test_token_abcdefghijklmnopqrstuvwxyz",
            session=AiohttpSession(api=TelegramAPIServer.from_base(origin)),
        )
        settings = BotSettings(
            api_limits=limits,
            checkout_limits=checkout_limits,
            webhook_max_inflight=4,
            webhook_processing_timeout_seconds=10,
            webhook_max_request_bytes=65536,
            notification_delivery_enabled=True,
            notification_delivery_key="owned-delivery-key-" + "a" * 32,
            notification_send_timeout_seconds=5,
            notification_lease_margin_seconds=1,
            notification_max_request_bytes=65536,
            telegram_token=bot.token,
            webhook_secret="controlled-secret",
            webhook_public_url=None,
            api_url=origin,
            api_key="controlled-key",
            api_timeout_seconds=5,
            listen_host="127.0.0.1",
            listen_port=0,
        )
        delivery_app = web.Application()
        register_delivery(delivery_app, bot, api, settings)
        delivery_runner = web.AppRunner(delivery_app, access_log=None)
        await delivery_runner.setup()
        await web.TCPSite(delivery_runner, "127.0.0.1", 0).start()
        delivery_origin = f"http://127.0.0.1:{delivery_runner.addresses[0][1]}"
        dispatcher = Dispatcher(disable_fsm=True)
        dispatcher.include_router(register(api, checkout_limits))
        delivery_key = settings.notification_delivery_key
        assert delivery_key is not None

        async def deliver():
            async with ClientSession() as client:
                async with client.post(
                    delivery_origin + "/internal/notifications/deliver",
                    json={"notification_id": 17, "claim_token": "b" * 64},
                    headers={
                        "X-Papilio-Delivery-Key": delivery_key
                    },
                ) as response:
                    return await response.json()

        async def callback(chat_type, identifier):
            update = Update.model_validate(
                {
                    "update_id": identifier,
                    "callback_query": {
                        "id": str(identifier),
                        "from": {
                            "id": 61,
                            "is_bot": False,
                            "first_name": "Owner",
                        },
                        "chat_instance": "controlled",
                        "data": "ci:12",
                        "message": {
                            "message_id": 10,
                            "date": 1,
                            "chat": {"id": 61, "type": chat_type},
                        },
                    },
                }
            )
            await dispatcher.feed_update(bot, update)

        try:
            self.assertEqual((await deliver())["outcome"], "accepted")
            keyboard = json.loads(sent[-1][1]["reply_markup"])
            button = keyboard["inline_keyboard"][0][0]
            self.assertEqual(button["callback_data"], "ci:12")
            self.assertNotIn("url", button)
            await callback("private", 1)
            self.assertEqual(calls[-1][0], "/v1/bot/checkouts/12/status")
            self.assertIn("لغو", sent[-2][1]["text"])
            count = len(calls)
            await callback("group", 2)
            self.assertEqual(len(calls), count)
            status_missing = True
            await callback("private", 3)
            self.assertEqual(calls[-1][0], "/v1/bot/checkouts/12/status")
            self.assertNotIn("service:", sent[-2][1].get("reply_markup", ""))
            action = {"kind": "subscription", "subscription_id": 91}
            self.assertEqual((await deliver())["outcome"], "accepted")
            self.assertIn("service:91", sent[-1][1]["reply_markup"])
            action = None
            self.assertEqual((await deliver())["outcome"], "accepted")
            self.assertNotIn("reply_markup", sent[-1][1])
            action = {"kind": "checkout", "checkout_id": 0}
            count = len(sent)
            self.assertEqual((await deliver())["outcome"], "retryable")
            self.assertEqual(len(sent), count)
        finally:
            await delivery_runner.cleanup()
            await api.close()
            await bot.session.close()
            await control_runner.cleanup()
