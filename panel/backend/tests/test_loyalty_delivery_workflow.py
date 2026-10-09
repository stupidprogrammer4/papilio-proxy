import asyncio
import socket
import sys
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import uvicorn
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiohttp import web

from src.config.settings import NotificationSettings
from tests.scheduler_runtime import exercise_native_loyalty_notifications
from tests.test_loyalty_workflow import LoyaltyWorkflowTest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "bot"))
from papilio_telegram.api import BotApi
from papilio_telegram.config import BotApiLimits, BotSettings
from papilio_telegram.delivery import register_delivery


async def owned_http(application):
    runner = web.AppRunner(application, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    try:
        await site.start()
    except BaseException:
        await runner.cleanup()
        raise
    return runner, f"http://127.0.0.1:{runner.addresses[0][1]}"


async def stop_owned_api(server, serving, listener):
    server.should_exit = True
    try:
        await serving
    finally:
        listener.close()


class LoyaltyDeliveryWorkflowTest(LoyaltyWorkflowTest):
    async def test_native_purchase_loyalty_scheduler_aiogram_delivery(self):
        await self.configure()
        preferences = (await self.get("/v1/admin/settings"))["data"]
        policy = preferences["values"]["notifications"]
        policy.update(
            enabled=True,
            channel_mode="both",
            delivery_enabled=True,
        )
        policy["templates"].update(
            tier_changed={
                "enabled": True,
                "title": "Tier changed",
                "body": "Your tier is {status}.",
            },
            discount_applied={
                "enabled": True,
                "title": "Purchase discount",
                "body": "You saved {amount_toman} toman on {id}.",
            },
        )
        response = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": preferences["revision"],
                "values": preferences["values"],
            },
        )
        self.assertEqual(response.status_code, 200)

        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        api_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                lifespan="off",
                access_log=False,
                log_level="error",
            )
        )
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        cleanup = AsyncExitStack()
        cleanup.push_async_callback(stop_owned_api, server, serving, listener)
        try:
            telegram_calls = []

            async def telegram_send(request):
                payload = dict(await request.post())
                telegram_calls.append(payload)
                return web.json_response(
                    {
                        "ok": True,
                        "result": {
                            "message_id": len(telegram_calls),
                            "date": int(datetime.now(UTC).timestamp()),
                            "chat": {
                                "id": int(payload["chat_id"]),
                                "type": "private",
                            },
                            "text": payload["text"],
                        },
                    }
                )

            telegram_application = web.Application(client_max_size=65536)
            telegram_application.router.add_post(
                "/bot{token}/sendMessage", telegram_send
            )
            telegram_runner, telegram_url = await owned_http(
                telegram_application
            )
            cleanup.push_async_callback(telegram_runner.cleanup)
            limits = BotApiLimits(65536, 4, 1024, 5, 5)
            api = BotApi(
                api_url, self.settings.security.bot_service_key, 5, limits
            )
            cleanup.push_async_callback(api.close)
            bot = Bot(
                "123456:testfixture",
                session=AiohttpSession(
                    api=TelegramAPIServer.from_base(telegram_url)
                ),
            )
            cleanup.push_async_callback(bot.session.close)
            delivery_key = uuid4().hex
            bot_settings = BotSettings(
                api_limits=limits,
                webhook_max_inflight=4,
                webhook_processing_timeout_seconds=5,
                webhook_max_request_bytes=4096,
                notification_delivery_enabled=True,
                notification_delivery_key=delivery_key,
                notification_send_timeout_seconds=5,
                notification_lease_margin_seconds=5,
                notification_max_request_bytes=4096,
                telegram_token="123456:testfixture",
                webhook_secret=uuid4().hex,
                webhook_public_url=None,
                api_url=api_url,
                api_key=self.settings.security.bot_service_key,
                api_timeout_seconds=5,
                listen_host="127.0.0.1",
                listen_port=0,
            )
            bridge_application = web.Application(client_max_size=4096)
            register_delivery(bridge_application, bot, api, bot_settings)
            bridge_runner, bridge_url = await owned_http(bridge_application)
            cleanup.push_async_callback(bridge_runner.cleanup)
            raw = self.settings.notifications.model_dump()
            raw.update(
                outbound_enabled=True,
                endpoint=bridge_url + "/internal/notifications/deliver",
                delivery_key=delivery_key,
                allow_loopback_http=True,
                scan_cron="* * * * *",
            )
            self.settings.notifications = NotificationSettings.model_validate(
                raw
            )
            self.raw["notifications"] = self.settings.notifications.model_dump(
                mode="json"
            )
            subscription, _, _, purchase = await self.setup_sale(
                quota_bytes=100 * 1024**3, protocols=("vless_reality",)
            )
            customer_id = subscription["customer_id"]
            customer = (await self.get(f"/v1/admin/customers/{customer_id}"))[
                "data"
            ]
            self.assertEqual(subscription["price_rial"], 90000)
            status = (
                await self.get(f"/v1/admin/loyalty/customers/{customer_id}")
            )["data"]
            self.assertEqual(status["tier"]["code"], "bronze")
            self.assertEqual(status["purchase_count"], 1)
            notices = await self.loyalty_notices(customer_id)
            self.assertEqual(
                {row["kind"] for row in notices},
                {"tier_changed", "discount_applied"},
            )
            self.assertEqual(len(notices), 2)
            replay = await self.post("/v1/admin/subscriptions", purchase)
            self.assertEqual(replay["id"], subscription["id"])
            replay_notices = await self.loyalty_notices(customer_id)
            self.assertEqual(
                [row["id"] for row in replay_notices],
                [row["id"] for row in notices],
            )
            result = await asyncio.to_thread(
                exercise_native_loyalty_notifications,
                self.raw,
                [row["id"] for row in notices],
            )
            self.assertEqual(result, (2, 2, 1))
            fresh = await self.loyalty_notices(customer_id)
            self.assertTrue(all(row["status"] == "delivered" for row in fresh))
            self.assertTrue(all(row["attempts"] == 1 for row in fresh))
            self.assertTrue(
                all(row["telegram_message_id"] is not None for row in fresh)
            )
            texts = [row["text"] for row in telegram_calls]
            for row in fresh:
                self.assertEqual(
                    sum(row["body"] in value for value in texts), 1
                )
            self.assertTrue(
                all(
                    int(row["chat_id"]) == customer["telegram_id"]
                    for row in telegram_calls
                )
            )
            wallet = (
                await self.get(f"/v1/admin/payments/wallets/{customer_id}")
            )["data"]
            self.assertEqual(wallet["balance_rial"], 210000)
        finally:
            await cleanup.aclose()

    async def loyalty_notices(self, customer_id):
        response = await self.client.get(
            "/v1/admin/notifications",
            headers=self.headers,
            params={"customer_id": customer_id},
        )
        self.assertEqual(response.status_code, 200)
        return [
            row
            for row in response.json()["data"]
            if row["kind"] in {"tier_changed", "discount_applied"}
        ]
