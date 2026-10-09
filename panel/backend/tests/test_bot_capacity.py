import asyncio
import gzip
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

import aiohttp
from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "bot"))
from papilio_telegram.admission import WebhookAdmission
from papilio_telegram.api import BotApi, BotApiError
from papilio_telegram.config import BotApiLimits
from papilio_telegram.webhook import ForegroundRequestHandler


class BotCapacityTest(IsolatedAsyncioTestCase):
    def test_deadlines_require_finite_positive_values(self):
        for deadline in (float("nan"), float("inf"), 0, -1):
            with self.assertRaises(ValueError):
                WebhookAdmission(1, 64, deadline)
            with self.assertRaises(ValueError):
                BotApi(
                    "http://127.0.0.1",
                    "fixture",
                    deadline,
                    BotApiLimits(1024, 2, 256, 1, 1),
                )

    async def test_bounded_network_failures_and_connection_recovery(self):
        compressed = gzip.compress(b'{"data":"' + b"x" * 1_000_000 + b'"}')

        async def respond(request):
            self.assertEqual(
                request.headers["X-Papilio-Bot-Key"], "controlled-test-key"
            )
            mode = request.match_info["mode"]
            if mode == "compressed":
                return web.Response(
                    body=compressed, headers={"Content-Encoding": "gzip"}
                )
            if mode == "chunked":
                response = web.StreamResponse()
                await response.prepare(request)
                await response.write(b"x" * 2048)
                await response.write_eof()
                return response
            if mode == "large":
                return web.Response(body=b"x" * 2048)
            if mode == "error":
                return web.json_response(
                    {"error": {"message_code": "wallet_insufficient"}},
                    status=409,
                )
            return web.json_response({"data": {"price_rial": 12000}})

        app = web.Application()
        app.router.add_get("/v1/bot/{mode}", respond)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        api = BotApi(
            f"http://127.0.0.1:{runner.addresses[0][1]}",
            "controlled-test-key",
            2,
            BotApiLimits(1024, 2, 256, 1, 1),
        )
        try:

            async def assert_denied(mode, code):
                with self.assertRaises(BotApiError) as denied:
                    await api.call("/v1/bot/" + mode)
                self.assertEqual(denied.exception.code, code)

            await asyncio.gather(
                assert_denied("large", "response_too_large"),
                assert_denied("chunked", "response_too_large"),
                assert_denied("compressed", "response_encoding_unsupported"),
                assert_denied("error", "wallet_insufficient"),
            )
            replies = await asyncio.gather(
                *(api.call("/v1/bot/small") for _ in range(12))
            )
            self.assertTrue(
                all(row["data"]["price_rial"] == 12000 for row in replies)
            )
            resource = api.client
            assert resource is not None
            await api.close()
            self.assertTrue(resource.closed)
        finally:
            await api.close()
            await runner.cleanup()

    async def test_admission_and_request_capacity_release(self):
        admission = WebhookAdmission(1, 64, 2)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def handler(request):
            entered.set()
            await release.wait()
            return web.json_response({"ok": True})

        app = web.Application(
            client_max_size=64, middlewares=[admission.middleware]
        )
        app.router.add_post("/telegram/webhook", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        url = f"http://127.0.0.1:{runner.addresses[0][1]}/telegram/webhook"
        try:
            async with aiohttp.ClientSession() as client:
                first = asyncio.create_task(client.post(url, data=b"{}"))
                await asyncio.wait_for(entered.wait(), 2)
                async with client.post(url, data=b"{}") as extra:
                    self.assertEqual(extra.status, 503)
                self.assertEqual(admission.active, 1)
                release.set()
                response = await first
                self.assertEqual(response.status, 200)
                response.close()
                self.assertEqual(admission.active, 0)
                async with client.post(url, data=b"x" * 65) as oversized:
                    self.assertEqual(oversized.status, 413)
                self.assertEqual(admission.active, 0)
        finally:
            release.set()
            await runner.cleanup()

    async def test_native_webhook_deadline_cancels_and_recovers(self):
        admission = WebhookAdmission(1, 4096, 0.1)
        dispatcher = Dispatcher(disable_fsm=True)
        router = Router()
        cancelled = asyncio.Event()
        completed = asyncio.Event()
        blocked = asyncio.Event()

        @router.message()
        async def receive(message: Message):
            if message.text == "block":
                try:
                    await blocked.wait()
                finally:
                    cancelled.set()
            else:
                completed.set()

        dispatcher.include_router(router)
        bot = Bot(token="123456:controlled-test-token")
        app = web.Application(middlewares=[admission.middleware])
        handler = ForegroundRequestHandler(
            dispatcher=dispatcher,
            bot=bot,
            secret_token="controlled-secret",
            handle_in_background=False,
        )
        handler.register(app, path="/telegram/webhook")
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        url = f"http://127.0.0.1:{runner.addresses[0][1]}/telegram/webhook"
        update = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "date": 1700000000,
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 1, "is_bot": False, "first_name": "Test"},
                "text": "block",
            },
        }
        headers = {"X-Telegram-Bot-Api-Secret-Token": "controlled-secret"}
        try:
            async with aiohttp.ClientSession() as client:
                async with client.post(url, json=update) as unauthorized:
                    self.assertEqual(unauthorized.status, 401)
                self.assertFalse(cancelled.is_set())
                async with client.post(
                    url, json=update, headers=headers
                ) as expired:
                    self.assertEqual(expired.status, 503)
                self.assertTrue(cancelled.is_set())
                self.assertEqual(admission.active, 0)
                update["update_id"] = 2
                update["message"]["text"] = "complete"
                async with client.post(
                    url, json=update, headers=headers
                ) as recovered:
                    self.assertEqual(recovered.status, 200)
                self.assertTrue(completed.is_set())
                self.assertEqual(admission.active, 0)
                async with client.post(
                    url, json={}, headers=headers
                ) as malformed:
                    self.assertEqual(malformed.status, 400)
                async with client.post(
                    url, data=b"[1]", headers=headers
                ) as invalid:
                    self.assertEqual(invalid.status, 400)
        finally:
            await runner.cleanup()
            await bot.session.close()
            await dispatcher.storage.close()
