"""Native checkout transitions and queue delivery into actual aiogram."""

import asyncio
import json
import socket
import sys
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.types import Update
from aiohttp import web
from papilio.api.application import create_app
from papilio.infra.db.transaction import transaction
from papilio_tasks.apps.lifecycle import Producers
from papilio_tasks.apps.schedulers.redis import create_app as tasks_app
from redis.asyncio import Redis
from sqlalchemy import text

from src.config.providers import infrastructure_providers, task_providers
from src.config.settings import NotificationSettings, PapilioSettings
from src.modules.sales.checkout.interfaces import ICheckoutRecoveryRunner
from tests.scheduler_runtime import exercise_native_loyalty_notifications
from tests.test_loyalty_delivery_workflow import owned_http, stop_owned_api
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowFixture,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "bot"))
from papilio_telegram.api import BotApi
from papilio_telegram.checkout import (
    CheckoutCancel,
    CheckoutCreate,
    CheckoutDraftLimits,
)
from papilio_telegram.config import BotApiLimits, BotSettings
from papilio_telegram.delivery import register_delivery
from papilio_telegram.handlers import register


class CheckoutNoticeDeliveryWorkflowTest(StaffAdministrationWorkflowFixture):
    async def configure_checkout(self):
        self.raw["purchase_intents"] = {
            "policy": {
                "enabled": True,
                "admission_mode": "allow_manual_profiles",
                "default_expiry_seconds": 3600,
            },
            "scan_cron": "* * * * *",
            "recheck_seconds": 1,
        }
        self.checkout_namespace = "papilio:test:checkoutnotice:" + uuid4().hex
        self.raw["tasks"]["scheduler"].update(
            queue_name=self.checkout_namespace + ":jobs",
            schedule_prefix=self.checkout_namespace + ":schedules",
            result_prefix=self.checkout_namespace + ":results",
        )
        await self.client.aclose()
        await self.app.state.dishka_container.close()
        self.settings = PapilioSettings.model_validate(self.raw)
        native = tasks_app(
            self.settings.tasks.scheduler,
            providers=task_providers(self.settings),
            modules=self.settings.app.modules,
        )
        self.checkout_producers = Producers(native)
        await self.checkout_producers.connect()
        self.app = create_app(
            self.settings,
            providers=infrastructure_providers(self.settings),
            middleware=(),
            docs_url=None,
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="https://admin.example.com",
        )
        login = await self.client.post(
            "/v1/admin/auth/login",
            headers={"Origin": self.settings.public.admin_origin},
            json={"username": self.username, "password": self.password},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.headers = {
            "Origin": self.settings.public.admin_origin,
            "X-CSRF-Token": login.json()["csrf_token"],
        }
        preferences = (await self.get("/v1/admin/settings"))["data"]
        policy = preferences["values"]["notifications"]
        policy.update(enabled=True, channel_mode="both", delivery_enabled=True)
        policy["templates"].update(
            checkout_action_required={
                "enabled": True,
                "title": "Checkout review",
                "body": "Review {id}: {status}, {amount_toman} toman.",
            },
            checkout_cancelled={
                "enabled": True,
                "title": "Checkout cancelled",
                "body": "Cancelled {id}: {status}, {amount_toman} toman.",
            },
            checkout_expired={
                "enabled": True,
                "title": "Checkout expired",
                "body": "Expired {id}: {status}, {amount_toman} toman.",
            },
        )
        saved = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": preferences["revision"],
                "values": preferences["values"],
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)

    async def asyncTearDown(self):
        producers = getattr(self, "checkout_producers", None)
        if producers is not None:
            await producers.stop()
            client = Redis.from_url(self.raw["redis"]["url"])
            keys = [
                key
                async for key in client.scan_iter(
                    match=self.checkout_namespace + ":*"
                )
            ]
            if keys:
                await client.delete(*keys)
            await client.aclose()
        await super().asyncTearDown()

    async def create_intent(self, api, telegram_id, suffix):
        plan = await self.post(
            "/v1/admin/plans",
            {
                "code": "notice_" + suffix + "_" + self.suffix,
                "title": "Checkout notice plan",
                "quota_bytes": 123456789,
                "duration_days": 19,
                "price_rial": 120005,
            },
        )
        active = await self.client.patch(
            f"/v1/admin/plans/{plan['id']}/active",
            headers=self.headers,
            json={"is_active": True},
        )
        self.assertEqual(active.status_code, 200, active.text)
        offer = await api.checkout_offer(
            plan["id"], telegram_id, "Notice owner"
        )
        intent = await api.checkout_create(
            telegram_id,
            "Notice owner",
            CheckoutCreate(
                request_key="notice_" + uuid4().hex,
                plan_id=plan["id"],
                funding_mode="wallet_only",
                expected_offer_sha256=offer.offer_sha256,
                expected_price_rial=offer.price_rial,
                auto_renew=False,
                expiry_seconds=offer.default_expiry_seconds,
                changed_offer_action="require_confirmation",
            ),
        )
        return plan, intent

    async def recover(self, intent_id):
        async with self.app.state.dishka_container() as scope:
            runner = await scope.get(ICheckoutRecoveryRunner)
            result = await runner.run(intent_id)
        return result

    async def notices(self, customer_id):
        response = await self.client.get(
            "/v1/admin/notifications",
            headers=self.headers,
            params={"customer_id": customer_id},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return [
            row
            for row in response.json()["data"]
            if row["kind"].startswith("checkout_")
        ]

    async def test_native_checkout_transitions_scheduler_aiogram_owned_actions(
        self,
    ):
        await self.configure_checkout()
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        api_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(
            uvicorn.Config(
                self.app, lifespan="off", access_log=False, log_level="error"
            )
        )
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        cleanup = AsyncExitStack()
        cleanup.push_async_callback(stop_owned_api, server, serving, listener)
        try:
            telegram_calls = []

            async def telegram(request):
                payload = dict(await request.post())
                method = request.match_info["method"]
                telegram_calls.append((method, payload))
                result = (
                    True
                    if method == "answerCallbackQuery"
                    else {
                        "message_id": len(telegram_calls),
                        "date": int(datetime.now(UTC).timestamp()),
                        "chat": {
                            "id": int(payload["chat_id"]),
                            "type": "private",
                        },
                        "text": payload["text"],
                    }
                )
                return web.json_response({"ok": True, "result": result})

            telegram_app = web.Application(client_max_size=65536)
            telegram_app.router.add_post("/bot{token}/{method}", telegram)
            telegram_runner, telegram_url = await owned_http(telegram_app)
            cleanup.push_async_callback(telegram_runner.cleanup)
            limits = BotApiLimits(65536, 4, 1024, 5, 5)
            drafts = CheckoutDraftLimits(20, 60, 5)
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
                checkout_limits=drafts,
                webhook_max_inflight=4,
                webhook_processing_timeout_seconds=5,
                webhook_max_request_bytes=4096,
                notification_delivery_enabled=True,
                notification_delivery_key=delivery_key,
                notification_send_timeout_seconds=5,
                notification_lease_margin_seconds=5,
                notification_max_request_bytes=4096,
                telegram_token=bot.token,
                webhook_secret=uuid4().hex,
                webhook_public_url=None,
                api_url=api_url,
                api_key=self.settings.security.bot_service_key,
                api_timeout_seconds=5,
                listen_host="127.0.0.1",
                listen_port=0,
            )
            bridge = web.Application(client_max_size=4096)
            register_delivery(bridge, bot, api, bot_settings)
            bridge_runner, bridge_url = await owned_http(bridge)
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
            owner = int(self.suffix[:10], 16)
            changed_plan, changed = await self.create_intent(
                api, owner, "changed"
            )
            edited = await self.client.patch(
                f"/v1/admin/plans/{changed_plan['id']}",
                headers=self.headers,
                json={"price_rial": 120015},
            )
            self.assertEqual(edited.status_code, 200, edited.text)
            self.assertEqual(
                (await self.recover(changed.id)).state, "action_required"
            )
            _, cancelled = await self.create_intent(api, owner, "cancelled")
            cancel_key = "cancel_" + uuid4().hex
            cancellation = CheckoutCancel(
                request_key=cancel_key, expected_revision=cancelled.revision
            )
            result = await api.checkout_cancel(
                cancelled.id,
                owner,
                "Notice owner",
                cancellation,
            )
            self.assertEqual(result.state, "cancelled")
            _, expired = await self.create_intent(api, owner, "expired")
            async with self.connection.uow() as unit:
                async with transaction(unit):
                    await unit.execute(
                        text(
                            "UPDATE tbl_checkout_intents SET expires_at="
                            "UTC_TIMESTAMP()-INTERVAL 1 SECOND WHERE id=:id"
                        ),
                        {"id": expired.id},
                    )
            self.assertEqual((await self.recover(expired.id)).state, "expired")
            notices = await self.notices(changed.customer_id)
            self.assertEqual(
                {row["kind"] for row in notices},
                {
                    "checkout_action_required",
                    "checkout_cancelled",
                    "checkout_expired",
                },
            )
            self.assertEqual(len(notices), 3)
            await api.checkout_cancel(
                cancelled.id,
                owner,
                "Notice owner",
                cancellation,
            )
            repeated = await api.checkout_cancel(
                cancelled.id,
                owner,
                "Notice owner",
                CheckoutCancel(
                    request_key="cancel_again_" + uuid4().hex,
                    expected_revision=result.revision,
                ),
            )
            self.assertEqual(repeated.revision, result.revision)
            self.assertEqual(len(await self.notices(changed.customer_id)), 3)
            delivered = await asyncio.to_thread(
                exercise_native_loyalty_notifications,
                self.raw,
                [row["id"] for row in notices],
            )
            self.assertEqual(delivered, (3, 3, 1))
            fresh = await self.notices(changed.customer_id)
            self.assertTrue(all(row["status"] == "delivered" for row in fresh))
            sends = [
                body
                for method, body in telegram_calls
                if method == "sendMessage"
            ]
            self.assertEqual(len(sends), 3)
            self.assertEqual(
                {body["text"] for body in sends},
                {row["title"] + "\n" + row["body"] for row in notices},
            )
            self.assertEqual({int(body["chat_id"]) for body in sends}, {owner})
            self.assertEqual(
                {
                    json.loads(body["reply_markup"])["inline_keyboard"][0][0][
                        "callback_data"
                    ]
                    for body in sends
                },
                {f"ci:{changed.id}", f"ci:{cancelled.id}", f"ci:{expired.id}"},
            )
            self.assertFalse(
                any('"url"' in body["reply_markup"] for body in sends)
            )
            dispatcher = Dispatcher(disable_fsm=True)
            dispatcher.include_router(register(api, drafts))

            async def callback(identity, chat_type, sequence):
                await dispatcher.feed_update(
                    bot,
                    Update.model_validate(
                        {
                            "update_id": sequence,
                            "callback_query": {
                                "id": str(sequence),
                                "from": {
                                    "id": identity,
                                    "is_bot": False,
                                    "first_name": "Owner",
                                },
                                "chat_instance": "owned",
                                "data": f"ci:{changed.id}",
                                "message": {
                                    "message_id": 10,
                                    "date": 1,
                                    "chat": {
                                        "id": identity,
                                        "type": chat_type,
                                    },
                                },
                            },
                        }
                    ),
                )

            await callback(owner, "private", 1)
            self.assertIn("نیازمند تأیید", telegram_calls[-2][1]["text"])
            await callback(owner + 1, "private", 2)
            self.assertNotIn(
                "co:", telegram_calls[-2][1].get("reply_markup", "")
            )
            before_group = len(telegram_calls)
            await callback(owner, "group", 3)
            self.assertEqual(len(telegram_calls), before_group + 1)
            async with self.connection.uow() as unit:
                counts = (
                    await unit.execute(
                        text(
                            "SELECT (SELECT COUNT(*) FROM tbl_subscriptions),"
                            "(SELECT COUNT(*) FROM tbl_wallet_entries "
                            "WHERE reason='purchase')"
                        )
                    )
                ).one()
            self.assertEqual(tuple(counts), (0, 0))
        finally:
            await cleanup.aclose()
