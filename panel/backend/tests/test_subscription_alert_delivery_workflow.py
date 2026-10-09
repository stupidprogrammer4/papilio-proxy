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
from papilio.infra.db.transaction import transaction
from sqlalchemy import update
from sqlmodel import col

from src.config.settings import NotificationSettings
from src.modules.accounts.customers.infra.tables import CustomerTable
from tests.scheduler_runtime import exercise_native_loyalty_notifications
from tests.test_subscription_alerts_workflow import (
    SubscriptionAlertsWorkflowTest,
)

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


class SubscriptionAlertDeliveryWorkflowTest(SubscriptionAlertsWorkflowTest):
    async def test_native_alert_notifications_aiogram_owned_action(self):
        preferences = await self.configure_alerts()
        preferences["values"]["notifications"].update(
            channel_mode="both", delivery_enabled=True
        )
        saved = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": preferences["revision"],
                "values": preferences["values"],
            },
        )
        self.assertEqual(saved.status_code, 200)
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
            customer, subscription = await self.paid_subscription()
            telegram_id = int(uuid4().hex[:12], 16)
            async with self.connection.uow() as unit:
                async with transaction():
                    await unit.execute(
                        update(CustomerTable)
                        .where(col(CustomerTable.id) == customer["id"])
                        .values(telegram_id=telegram_id)
                    )
            await self.change(
                subscription["id"], status="active", used_bytes=950000000
            )
            await self.post(
                f"/v1/admin/subscriptions/attention/{subscription['id']}/check"
            )
            notices = [
                row
                for row in await self.notices(customer["id"])
                if row["subscription_context"] is not None
            ]
            self.assertEqual(len(notices), 3)
            result = await asyncio.to_thread(
                exercise_native_loyalty_notifications,
                self.raw,
                [row["id"] for row in notices],
            )
            self.assertEqual(result, (3, 3, 1))
            fresh = [
                row
                for row in await self.notices(customer["id"])
                if row["subscription_context"] is not None
            ]
            self.assertTrue(all(row["status"] == "delivered" for row in fresh))
            alert_calls = [
                call
                for call in telegram_calls
                if any(
                    call["text"] == row["title"] + "\n" + row["body"]
                    for row in fresh
                )
            ]
            self.assertEqual(len(alert_calls), 3)
            self.assertTrue(
                all(
                    sum(
                        call["text"] == row["title"] + "\n" + row["body"]
                        for call in alert_calls
                    )
                    == 1
                    for row in fresh
                )
            )
            self.assertTrue(
                all(
                    int(row["chat_id"]) == telegram_id
                    for row in telegram_calls
                )
            )
            self.assertTrue(
                all(
                    f"service:{subscription['id']}" in row["reply_markup"]
                    for row in alert_calls
                )
            )
            self.assertFalse(
                any("https://" in row["reply_markup"] for row in alert_calls)
            )
            owned = await api.renewal_eligibility(
                telegram_id, customer["display_name"], subscription["id"]
            )
            self.assertEqual(owned.payer_kind, "self")
            self.assertEqual(owned.wallet_balance_rial, 200000)
        finally:
            await cleanup.aclose()
