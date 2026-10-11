"""Actual aiogram dispatch against controlled external HTTP boundaries."""

import json
import unittest

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.types import Update
from aiohttp import web

from papilio_telegram.api import BotApi
from papilio_telegram.checkout import CheckoutDraftLimits
from papilio_telegram.config import BotApiLimits
from papilio_telegram.handlers import register


class CheckoutConsumerTest(unittest.IsolatedAsyncioTestCase):
    async def test_durable_checkout_retry_resume_and_explicit_reconfirmation(
        self,
    ):
        calls = []
        telegram = []
        purchases = {}
        offer = {
            "customer_id": 7,
            "plan_id": 42,
            "price_rial": 101,
            "offer_sha256": "a" * 64,
            "plan_title": "Flexible",
            "quota_bytes": None,
            "duration_days": None,
            "membership_count": 0,
            "delivery_mode": "manual_profiles",
            "default_expiry_seconds": 777,
            "captured_at": "2026-10-08T00:00:00Z",
        }
        intent = {
            "id": 12,
            "customer_id": 7,
            "plan_id": 42,
            "revision": 1,
            "state": "awaiting_funding",
            "funding_mode": "approved_topup",
            "delivery_mode": "manual_profiles",
            "price_rial": 101,
            "offer_sha256": "a" * 64,
            "auto_renew": True,
            "expires_at": "2026-10-09T00:00:00Z",
            "changed_offer_action": "require_confirmation",
            "topup_id": 4,
            "subscription_id": None,
            "reason_code": None,
        }
        funding_policy = {
            "destination_mode": "required",
            "allowed_methods": ["card"],
            "minimum_topup_rial": 150,
            "maximum_topup_rial": 500,
        }
        destination = {
            "destination_id": 9,
            "title": "Controlled destination",
            "kind": "card",
            "account": "1111222233334444",
            "recipient": "Controlled",
            "bank_name": "Controlled bank",
            "instructions": "Controlled instructions",
            "is_active": True,
        }
        captured_instruction = dict(destination)
        captured_instruction.update(
            topup_id=4,
            requested_amount_rial=150,
            payable_amount_rial=200,
            payment_identifier_mode="rial_suffix4",
            payment_identifier_code4="0200",
        )
        lose_first_response = True
        fail_without_commit = False
        retirements = {}
        lose_retire_response = True
        retirement_override = None

        async def api_handler(request):
            nonlocal lose_first_response, lose_retire_response
            body = await request.json()
            path = request.path
            calls.append((path, body, dict(request.query)))
            if path.endswith("/retire"):
                key = body["request_key"]
                if retirement_override is not None:
                    return web.json_response(
                        {
                            "data": {
                                **retirement_override,
                                "request_key": key,
                            }
                        }
                    )
                if key not in retirements:
                    existing = purchases.get(key)
                    retirements[key] = {
                        "request_key": key,
                        "status": "purchased"
                        if existing is not None
                        and intent["state"] == "purchased"
                        else "retired",
                        "intent": dict(intent)
                        if existing is not None
                        else None,
                    }
                if lose_retire_response:
                    lose_retire_response = False
                    return web.Response(text="retirement response lost")
                return web.json_response({"data": retirements[key]})
            if path.endswith("/funding"):
                return web.json_response({"data": funding_policy})
            if path.endswith("/destinations"):
                return web.json_response(
                    {
                        "data": [destination],
                        "meta": {
                            "pager": {"total_pages": 2},
                        },
                    }
                )
            if path.endswith("/payment-instruction"):
                return web.json_response({"data": captured_instruction})
            if "/offers/" in path:
                return web.json_response({"data": offer})
            if path.endswith("/lookup"):
                result = purchases.get(body["request_key"])
                if result is None:
                    return web.json_response(
                        {
                            "error": {
                                "message_code": "checkout_not_found",
                            }
                        },
                        status=404,
                    )
                return web.json_response({"data": result})
            if path.endswith("/history"):
                return web.json_response(
                    {
                        "data": [intent],
                        "meta": {
                            "pager": {"total_pages": 2},
                        },
                    }
                )
            if path.endswith("/status"):
                return web.json_response({"data": intent})
            if path.endswith("/reconfirm"):
                intent.update(
                    state="ready",
                    revision=3,
                    price_rial=offer["price_rial"],
                    offer_sha256=offer["offer_sha256"],
                )
                return web.json_response({"data": intent})
            if path.endswith("/cancel"):
                return web.json_response(
                    {
                        "error": {
                            "message_code": "checkout_revision_conflict",
                        }
                    },
                    status=409,
                )
            if path == "/v1/bot/checkouts":
                key = body["request_key"]
                if fail_without_commit:
                    return web.Response(
                        text="create response lost before commit"
                    )
                purchases.setdefault(key, dict(intent))
                if lose_first_response:
                    lose_first_response = False
                    # Committed remote operation, intentionally lost HTTP body.
                    return web.Response(text="interrupted response")
                return web.json_response({"data": purchases[key]})
            self.fail(f"Unexpected API request {path}")

        async def telegram_handler(request):
            data = dict(await request.post())
            method = request.match_info["method"]
            telegram.append((method, data))
            result = (
                True
                if method == "answerCallbackQuery"
                else {
                    "message_id": len(telegram),
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
        await web.TCPSite(runner, "127.0.0.1", 0).start()
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

        def dispatcher():
            result = Dispatcher(disable_fsm=True)
            result.include_router(register(api, CheckoutDraftLimits(2, 90, 3)))
            return result

        current = dispatcher()

        async def feed(identifier, data, chat_type="private"):
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
                            "message_id": 77,
                            "date": 1,
                            "chat": {"id": 61, "type": chat_type},
                        },
                    },
                }
            )
            await current.feed_update(bot, update)

        def buttons():
            return json.loads(telegram[-2][1]["reply_markup"])[
                "inline_keyboard"
            ]

        try:
            await feed(1, "plan:42")
            self.assertIn("تحویل دستی", telegram[-2][1]["text"])
            funding_callback = buttons()[3][0]["callback_data"]
            alternate_callback = buttons()[0][0]["callback_data"]
            await feed(101, funding_callback)
            self.assertIn("۱۵ تومان", telegram[-2][1]["text"])
            select_destination = buttons()[0][0]["callback_data"]
            await feed(102, select_destination)
            self.assertIn("Controlled destination", telegram[-2][1]["text"])
            create_callback = buttons()[0][0]["callback_data"]
            self.assertLessEqual(len(create_callback.encode()), 64)
            await feed(2, create_callback)
            self.assertIn("پاسخ خرید مشخص نیست", telegram[-2][1]["text"])
            await feed(3, alternate_callback)
            creations = [
                row[1] for row in calls if row[0] == "/v1/bot/checkouts"
            ]
            self.assertEqual(len(creations), 1)
            self.assertEqual(calls[-1][0], "/v1/bot/checkouts/lookup")
            self.assertEqual(
                calls[-1][1]["request_key"], creations[0]["request_key"]
            )
            self.assertEqual(creations[0]["expiry_seconds"], 777)
            self.assertEqual(creations[0]["funding_mode"], "approved_topup")
            self.assertEqual(creations[0]["topup_amount_rial"], 150)
            self.assertEqual(creations[0]["destination_id"], 9)
            self.assertEqual(len(purchases), 1)
            self.assertNotIn("payer_customer_id", creations[0])
            # Simulated process restart loses drafts, retains remote intent.
            current = dispatcher()
            await feed(4, create_callback)
            self.assertEqual(calls[-1][0], "/v1/bot/checkouts/lookup")
            self.assertEqual(len(purchases), 1)
            destination["account"] = "9999888877776666"
            await feed(104, "cp:12")
            self.assertIn("1111222233334444", telegram[-2][1]["text"])
            self.assertNotIn("9999888877776666", telegram[-2][1]["text"])
            self.assertIn("۲۰۰ ریال", telegram[-2][1]["text"])
            self.assertIn("۰۲۰۰", telegram[-2][1]["text"])
            self.assertIn("تمام مبلغ", telegram[-2][1]["text"])
            self.assertEqual(telegram[-2][1]["parse_mode"], "HTML")
            self.assertIn("<code>200</code>", telegram[-2][1]["text"])
            self.assertEqual(
                buttons()[0][0]["copy_text"]["text"], "1111222233334444"
            )
            self.assertEqual(buttons()[1][0]["copy_text"]["text"], "200")
            await feed(5, "cb:0000000000000000:w:0")
            self.assertIn("هنوز مشخص نیست", telegram[-2][1]["text"])
            self.assertEqual(len(purchases), 1)
            self.assertTrue(
                any(
                    button["callback_data"].startswith("cx:")
                    for row in buttons()
                    for button in row
                )
            )
            await feed(6, "ch:2")
            self.assertEqual(calls[-1][2], {"page": "2", "per_page": "3"})
            intent.update(state="action_required", revision=2)
            offer.update(price_rial=202, offer_sha256="b" * 64)
            await feed(7, "co:12")
            self.assertIn("۲۰٫۲ تومان", telegram[-2][1]["text"])
            reconfirm = buttons()[0][0]["callback_data"]
            await feed(8, reconfirm)
            self.assertEqual(calls[-1][1]["expected_revision"], 2)
            self.assertEqual(calls[-1][1]["expected_price_rial"], 202)
            await feed(9, "cc:12:2")
            self.assertIn("وضعیت و شرایط", telegram[-2][1]["text"])
            intent.update(state="purchased", subscription_id=92)
            await feed(10, "ci:12")
            self.assertIn("تحویل دستی هنوز", telegram[-2][1]["text"])
            funding_policy["maximum_topup_rial"] = 160
            await feed(105, "plan:42")
            await feed(106, buttons()[2][0]["callback_data"])
            self.assertIn("سقف", telegram[-2][1]["text"])
            self.assertEqual(len(purchases), 1)
            # New unresolved operation; explicit retirement fences late create.
            fail_without_commit = True
            await feed(107, "plan:42")
            unresolved_callback = buttons()[0][0]["callback_data"]
            await feed(108, unresolved_callback)
            retirement_review = buttons()[1][0]["callback_data"]
            await feed(109, retirement_review)
            retirement_callback = buttons()[0][0]["callback_data"]
            await feed(110, retirement_callback)
            self.assertIn("پاسخ لغو مشخص نیست", telegram[-2][1]["text"])
            create_count = sum(
                path == "/v1/bot/checkouts" for path, _, _ in calls
            )
            await feed(111, unresolved_callback)
            self.assertIn(
                "ثبت خرید قبلی را تکرار نکنید", telegram[-2][1]["text"]
            )
            self.assertEqual(
                create_count,
                sum(path == "/v1/bot/checkouts" for path, _, _ in calls),
            )
            self.assertFalse(
                any(
                    button["callback_data"].startswith("plan:")
                    for row in buttons()
                    for button in row
                )
            )
            current = dispatcher()
            await feed(112, retirement_callback)
            self.assertIn("به صورت قطعی بسته شد", telegram[-2][1]["text"])
            self.assertEqual(buttons()[0][0]["callback_data"], "plan:42")
            retirement_calls = [
                body for path, body, _ in calls if path.endswith("/retire")
            ]
            self.assertEqual(retirement_calls[0], retirement_calls[1])
            original_nonce = create_callback.split(":")[1]
            await feed(113, f"ct:{original_nonce}:42")
            self.assertIn("همان سرویس حفظ می‌شود", telegram[-2][1]["text"])
            self.assertTrue(
                any(
                    button["callback_data"] == "service:92"
                    for row in buttons()
                    for button in row
                )
            )
            self.assertEqual(len(purchases), 1)
            retirement_override = {"status": "retired", "intent": dict(intent)}
            await feed(114, f"ct:{original_nonce}:42")
            self.assertIn("پاسخ لغو مشخص نیست", telegram[-2][1]["text"])
            self.assertFalse(
                any(
                    button["callback_data"].startswith("plan:")
                    for row in buttons()
                    for button in row
                )
            )
            retirement_override = {
                "status": "purchased",
                "intent": {
                    **intent,
                    "state": "ready",
                    "subscription_id": None,
                },
            }
            await feed(115, f"ct:{original_nonce}:42")
            self.assertIn("پاسخ لغو مشخص نیست", telegram[-2][1]["text"])
            self.assertFalse(
                any(
                    button["callback_data"].startswith("plan:")
                    for row in buttons()
                    for button in row
                )
            )
            before = len(calls)
            await feed(116, f"ct:{original_nonce}:42", "group")
            self.assertEqual(len(calls), before)
            await feed(11, "ch:1", "group")
            self.assertEqual(len(calls), before)
        finally:
            await api.close()
            await bot.session.close()
            await runner.cleanup()
