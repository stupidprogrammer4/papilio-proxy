import asyncio
import sys
from contextvars import Context
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from aiohttp import web
from papilio.infra.db.transaction import transaction
from sqlalchemy import text, update

from src.config.settings import NotificationSettings
from src.modules.operations.notifications.domain.results import DeliveryOutcome
from src.modules.operations.notifications.infra.tables import NotificationTable
from src.modules.operations.notifications.infra.transport import (
    AiogramNotificationTransport,
)
from src.modules.operations.notifications.interfaces import (
    INotificationDeliveryCommand,
    INotificationDeliveryHandler,
    INotificationTransport,
)
from tests.test_support_workflow import SupportWorkflowTest


class NotificationsWorkflowTest(SupportWorkflowTest):
    async def notification_policy(self, **changes):
        prefs = (await self.get("/v1/admin/settings"))["data"]
        prefs["values"]["notifications"].update(changes)
        response = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": prefs["revision"],
                "values": prefs["values"],
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    async def deliver(self, id):
        async with self.app.state.dishka_container() as scope:
            handler = await scope.get(INotificationDeliveryHandler)
            result = await handler.deliver(id)
        return result

    async def claim(self, id):
        async with self.app.state.dishka_container() as scope:
            command = await scope.get(INotificationDeliveryCommand)
            result = await command.claim(id)
        return result

    async def finish(self, id, token, outcome):
        async with self.app.state.dishka_container() as scope:
            command = await scope.get(INotificationDeliveryCommand)
            result = await command.finish(id, token, outcome)
        return result

    async def recover_notice(self, row, action="retry"):
        response = await self.client.put(
            f"/v1/admin/notifications/{row['id']}/recovery",
            headers=self.headers,
            json={
                "expected_revision": row["revision"],
                "reason": "بررسی نتیجه و بازیابی",
                "action": action,
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    async def manual_notice(self, customer_id, key=None):
        data = {
            "customer_id": customer_id,
            "request_key": key or uuid4().hex,
            "title": "پیام خصوصی",
            "body": "پیام آزمون بدون ارسال تلگرام",
        }
        row = await self.post("/v1/admin/notifications", data)
        return row, data

    async def adapter(self, handler):
        application = web.Application(client_max_size=4096)
        application.router.add_post("/deliver", handler)
        runner = web.AppRunner(application, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]
        raw = self.settings.notifications.model_dump()
        raw.update(
            outbound_enabled=True,
            endpoint=f"http://127.0.0.1:{port}/deliver",
            delivery_key=uuid4().hex,
            allow_loopback_http=True,
        )
        self.settings.notifications = NotificationSettings.model_validate(raw)
        self.raw["notifications"] = self.settings.notifications.model_dump(
            mode="json"
        )
        return runner

    async def authorize(self, id, token):
        response = await self.client.post(
            f"/v1/bot/notifications/{id}/authorize",
            headers={
                "X-Papilio-Bot-Key": (self.settings.security.bot_service_key)
            },
            json={"claim_token": token},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    async def test_inbox_payment_support_replays_privacy_and_scoped_staff(
        self,
    ):
        client, headers, customer_id = await self.account()
        other, _, other_id = await self.account()
        try:
            row, data = await self.manual_notice(customer_id)
            replay = await self.post("/v1/admin/notifications", data)
            self.assertEqual(row["id"], replay["id"])
            changed = await self.client.post(
                "/v1/admin/notifications",
                headers=self.headers,
                json={**data, "body": "متن متفاوت"},
            )
            self.assertEqual(changed.status_code, 409)
            notices = await client.get(
                "/v1/customer/notifications",
                params={"customer_id": other_id, "per_page": 1},
            )
            self.assertEqual(notices.status_code, 200)
            self.assertEqual(
                [n["id"] for n in notices.json()["data"]], [row["id"]]
            )
            private = notices.json()["data"][0]
            self.assertTrue(
                {
                    "claim_token",
                    "event_key",
                    "error_code",
                    "customer_id",
                    "status",
                }.isdisjoint(private)
            )
            self.assertEqual(
                (
                    await other.get(f"/v1/customer/notifications/{row['id']}")
                ).status_code,
                404,
            )
            self.assertEqual(
                (
                    await self.client.get("/v1/customer/notifications")
                ).status_code,
                401,
            )
            self.assertEqual(
                (
                    await client.put(
                        f"/v1/customer/notifications/{row['id']}/read",
                        json={"is_read": True},
                    )
                ).status_code,
                403,
            )
            read = await client.put(
                f"/v1/customer/notifications/{row['id']}/read",
                headers=headers,
                json={"is_read": True},
            )
            self.assertEqual(read.status_code, 200)
            self.assertTrue(read.json()["data"]["is_read"])
            self.assertEqual(
                (
                    await client.get(
                        "/v1/customer/notifications?is_read=false"
                    )
                ).json()["data"],
                [],
            )
            topup = await self.post(
                "/v1/admin/payments/topups",
                {"customer_id": customer_id, "amount_rial": 200_001},
            )
            approval = {"bank_reference": "notification_" + uuid4().hex}
            paid = await self.client.post(
                f"/v1/admin/payments/topups/{topup['id']}/approve",
                headers=self.headers,
                json=approval,
            )
            self.assertEqual(paid.status_code, 200)
            duplicate = await self.client.post(
                f"/v1/admin/payments/topups/{topup['id']}/approve",
                headers=self.headers,
                json=approval,
            )
            self.assertEqual(duplicate.status_code, 200)
            ticket = await self.post(
                "/v1/admin/support",
                {
                    "customer_id": customer_id,
                    "request_key": uuid4().hex,
                    "subject": "سوال",
                    "body": "پاسخ نخست مدیر",
                },
            )
            reply = {
                "request_key": uuid4().hex,
                "expected_revision": ticket["revision"],
                "body": "پاسخ بعدی",
            }
            replied = await self.client.post(
                f"/v1/admin/support/{ticket['id']}/messages",
                headers=self.headers,
                json=reply,
            )
            self.assertEqual(replied.status_code, 200)
            repeated = await self.client.post(
                f"/v1/admin/support/{ticket['id']}/messages",
                headers=self.headers,
                json=reply,
            )
            self.assertEqual(repeated.status_code, 200)
            inbox = await client.get("/v1/customer/notifications")
            self.assertEqual(len(inbox.json()["data"]), 4)
            payment = next(
                n
                for n in inbox.json()["data"]
                if n["kind"] == "payment_approved"
            )
            self.assertIn("20000.1", payment["body"])
            reader = await self.post(
                "/v1/admin/staff",
                {
                    "username": "notice_" + self.suffix,
                    "password": "notice888",
                    "is_active": True,
                    "scopes": ["notifications:read"],
                },
            )
            scoped, staff_headers = await self.login_staff(
                reader["username"], "notice888"
            )
            try:
                self.assertEqual(
                    (await scoped.get("/v1/admin/notifications")).status_code,
                    200,
                )
                self.assertEqual(
                    (
                        await scoped.post(
                            "/v1/admin/notifications",
                            headers=staff_headers,
                            json=data,
                        )
                    ).status_code,
                    403,
                )
                self.assertEqual(
                    (
                        await scoped.put(
                            f"/v1/admin/notifications/{row['id']}/recovery",
                            headers=staff_headers,
                            json={
                                "expected_revision": 1,
                                "reason": "بررسی مدیر",
                                "action": "retry",
                            },
                        )
                    ).status_code,
                    403,
                )
            finally:
                await scoped.aclose()
            await self.notification_policy(channel_mode="telegram")
            hidden, _ = await self.manual_notice(customer_id)
            self.assertFalse(hidden["inbox_visible"])
            self.assertEqual(
                (
                    await client.get(
                        f"/v1/customer/notifications/{hidden['id']}"
                    )
                ).status_code,
                404,
            )
            self.assertFalse(await self.deliver(hidden["id"]))
            self.assertEqual(
                (await self.get(f"/v1/admin/notifications/{hidden['id']}"))[
                    "data"
                ]["attempts"],
                0,
            )
            async with self.connection.uow() as unit:
                total = (
                    await unit.execute(
                        text("SELECT COUNT(*) FROM tbl_notifications")
                    )
                ).scalar_one()
                self.assertEqual(total, 5)
                self.assertEqual(
                    (
                        await unit.execute(
                            text(
                                "SELECT balance_rial FROM tbl_wallets "
                                "WHERE customer_id=:id"
                            ),
                            {"id": customer_id},
                        )
                    ).scalar_one(),
                    200_001,
                )
        finally:
            await asyncio.gather(client.aclose(), other.aclose())

    async def test_native_transport_reuses_connections_and_closes_pool(self):
        client, _, customer_id = await self.account()
        peers = []

        async def accept(request):
            peers.append(request.transport.get_extra_info("peername"))
            return web.json_response(
                {"outcome": "accepted", "message_id": len(peers)}
            )

        runner = await self.adapter(accept)
        try:
            await self.notification_policy(
                channel_mode="both", delivery_enabled=True
            )
            first, _ = await self.manual_notice(customer_id)
            second, _ = await self.manual_notice(customer_id)
            self.assertTrue(await self.deliver(first["id"]))
            self.assertTrue(await self.deliver(second["id"]))
            self.assertEqual(len(peers), 2)
            self.assertEqual(peers[0], peers[1])
            async with self.app.state.dishka_container() as scope:
                transport = await scope.get(INotificationTransport)
                self.assertIsInstance(transport, AiogramNotificationTransport)
                session = transport.session
            self.assertFalse(session.closed)
            await self.app.state.dishka_container.close()
            self.assertTrue(session.closed)
        finally:
            await runner.cleanup()
            await client.aclose()

    async def test_real_http_delivery_authorization_concurrency_and_recovery(
        self,
    ):
        client, _, customer_id = await self.account()
        mode = {"value": "accepted"}
        calls = []

        async def receive(request):
            self.assertEqual(
                request.headers["X-Papilio-Delivery-Key"],
                self.settings.notifications.delivery_key,
            )
            payload = await request.json()
            calls.append(payload["notification_id"])
            authorization = await self.authorize(
                payload["notification_id"], payload["claim_token"]
            )
            self.assertTrue(authorization["allowed"])
            self.assertEqual(
                (
                    await self.authorize(
                        payload["notification_id"], payload["claim_token"]
                    )
                )["allowed"],
                False,
            )
            if mode["value"] == "accepted":
                return web.json_response(
                    {"outcome": "accepted", "message_id": len(calls)}
                )
            return web.json_response(
                {
                    "outcome": mode["value"],
                    "error_code": "controlled_external_result",
                }
            )

        runner = await self.adapter(receive)
        try:
            await self.notification_policy(
                channel_mode="both", delivery_enabled=True
            )
            row, _ = await self.manual_notice(customer_id)
            winners = await asyncio.gather(
                asyncio.create_task(
                    self.deliver(row["id"]), context=Context()
                ),
                asyncio.create_task(
                    self.deliver(row["id"]), context=Context()
                ),
            )
            self.assertEqual(sorted(winners), [False, True])
            delivered = (
                await self.get(f"/v1/admin/notifications/{row['id']}")
            )["data"]
            self.assertEqual(delivered["status"], "delivered")
            self.assertEqual(delivered["attempts"], 1)
            self.assertEqual(calls, [row["id"]])
            self.assertFalse(await self.deliver(row["id"]))
            attempts = (
                await self.get(f"/v1/admin/notifications/{row['id']}/attempts")
            )["data"]
            self.assertEqual(attempts[0]["outcome"], "accepted")
            self.assertNotIn("claim_token", attempts[0])
            mode["value"] = "ambiguous"
            uncertain, _ = await self.manual_notice(customer_id)
            sent = await self.deliver(uncertain["id"])
            self.assertTrue(
                sent,
                {
                    "record": (
                        await self.get(
                            f"/v1/admin/notifications/{uncertain['id']}"
                        )
                    )["data"],
                    "calls": calls,
                },
            )
            uncertain = (
                await self.get(f"/v1/admin/notifications/{uncertain['id']}")
            )["data"]
            self.assertEqual(uncertain["status"], "ambiguous")
            self.assertFalse(await self.deliver(uncertain["id"]))
            recovered = await self.recover_notice(uncertain)
            stale = await self.client.put(
                f"/v1/admin/notifications/{uncertain['id']}/recovery",
                headers=self.headers,
                json={
                    "expected_revision": uncertain["revision"],
                    "reason": "نسخه قدیمی",
                    "action": "retry",
                },
            )
            self.assertEqual(stale.status_code, 409)
            mode["value"] = "accepted"
            sent_recovery = await self.deliver(recovered["id"])
            self.assertTrue(
                sent_recovery,
                {
                    "record": (
                        await self.get(
                            f"/v1/admin/notifications/{recovered['id']}"
                        )
                    )["data"],
                    "now": datetime.now(UTC).isoformat(),
                    "calls": calls,
                },
            )
            resumed = (
                await self.get(f"/v1/admin/notifications/{recovered['id']}")
            )["data"]
            self.assertEqual(resumed["status"], "delivered")
            self.assertEqual(resumed["attempts"], 2)
            self.assertEqual(
                len(
                    (
                        await self.get(
                            f"/v1/admin/notifications/{recovered['id']}/history"
                        )
                    )["data"]
                ),
                1,
            )
            held, _ = await self.manual_notice(customer_id)
            claim = await self.claim(held["id"])
            assert claim is not None
            async with self.connection.uow() as unit:
                async with transaction(unit):
                    await unit.execute(
                        update(NotificationTable)
                        .where(NotificationTable.id == held["id"])
                        .values(
                            lease_until=datetime.now(UTC).replace(tzinfo=None)
                            - timedelta(seconds=1)
                        )
                    )
            self.assertFalse(
                (await self.authorize(held["id"], claim.claim_token))[
                    "allowed"
                ]
            )
            self.assertIsNone(await self.claim(held["id"]))
            expired = (
                await self.get(f"/v1/admin/notifications/{held['id']}")
            )["data"]
            self.assertEqual(expired["status"], "ambiguous")
            self.assertFalse(
                await self.finish(
                    held["id"],
                    claim.claim_token,
                    DeliveryOutcome("accepted", message_id=99),
                )
            )
            cancelled = await self.recover_notice(expired, "cancel")
            self.assertEqual(cancelled["status"], "cancelled")
        finally:
            await runner.cleanup()
            await client.aclose()

    async def test_immediate_claim_respects_mysql_timestamp_precision(self):
        class FractionalClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz).replace(microsecond=700000)

        client, _, customer_id = await self.account()
        config = self.settings.notifications.model_dump()
        config.update(
            outbound_enabled=True,
            endpoint="http://127.0.0.1:1/deliver",
            delivery_key=uuid4().hex,
            allow_loopback_http=True,
        )
        self.settings.notifications = NotificationSettings.model_validate(
            config
        )
        try:
            await self.notification_policy(
                channel_mode="both", delivery_enabled=True
            )
            with patch(
                "src.modules.operations.notifications.app.commands.datetime",
                FractionalClock,
            ):
                row, _ = await self.manual_notice(customer_id)
                claim = await self.claim(row["id"])
                self.assertIsNotNone(claim)
                persisted = (
                    await self.get(f"/v1/admin/notifications/{row['id']}")
                )["data"]
                self.assertEqual(persisted["status"], "processing")
        finally:
            await client.aclose()

    async def test_native_scheduler_queue_worker_commits_notification_delivery(
        self,
    ):
        from tests.scheduler_runtime import exercise_native_notifications

        client, _, customer_id = await self.account()
        received = []

        async def receive(request):
            self.assertEqual(
                request.headers["X-Papilio-Delivery-Key"],
                self.settings.notifications.delivery_key,
            )
            payload = await request.json()
            authorization = await self.authorize(
                payload["notification_id"], payload["claim_token"]
            )
            self.assertTrue(authorization["allowed"])
            received.append(payload["notification_id"])
            return web.json_response({"outcome": "accepted", "message_id": 71})

        runner = await self.adapter(receive)
        try:
            await self.notification_policy(
                channel_mode="both", delivery_enabled=True
            )
            row, _ = await self.manual_notice(customer_id)
            result = await asyncio.to_thread(
                exercise_native_notifications, self.raw, row["id"]
            )
            self.assertEqual(result, ("delivered", 1, "accepted"))
            self.assertEqual(received, [row["id"]])
            fresh = (await self.get(f"/v1/admin/notifications/{row['id']}"))[
                "data"
            ]
            self.assertEqual(fresh["telegram_message_id"], 71)
            self.assertEqual(
                (
                    await client.get(f"/v1/customer/notifications/{row['id']}")
                ).status_code,
                200,
            )
        finally:
            await runner.cleanup()
            await client.aclose()

    async def test_real_aiogram_bridge_with_controlled_telegram_http(self):
        import aiohttp
        from aiogram import Bot
        from aiogram.client.session.aiohttp import AiohttpSession
        from aiogram.client.telegram import TelegramAPIServer

        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "bot"))
        from papilio_telegram.api import BotApi
        from papilio_telegram.config import BotSettings
        from papilio_telegram.delivery import register_delivery

        async def start_server(application):
            runner = web.AppRunner(application, access_log=None)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            return runner, f"http://127.0.0.1:{runner.addresses[0][1]}"

        client, _, customer_id = await self.account()
        telegram_mode = {"value": "accepted"}
        telegram_calls = []

        async def telegram_send(request):
            payload = await request.post()
            telegram_calls.append(dict(payload))
            if telegram_mode["value"] == "rate_limit":
                return web.json_response(
                    {
                        "ok": False,
                        "error_code": 429,
                        "description": "Too Many Requests: retry after 1",
                        "parameters": {"retry_after": 1},
                    },
                    status=429,
                )
            if telegram_mode["value"] == "forbidden":
                return web.json_response(
                    {
                        "ok": False,
                        "error_code": 403,
                        "description": "Forbidden: bot was blocked "
                        "by the user",
                    },
                    status=403,
                )
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
        telegram_runner, telegram_url = await start_server(
            telegram_application
        )

        async def native_api_gateway(request):
            response = await self.client.post(
                request.path,
                headers={
                    "X-Papilio-Bot-Key": request.headers.get(
                        "X-Papilio-Bot-Key", ""
                    )
                },
                json=await request.json(),
            )
            return web.json_response(
                response.json(), status=response.status_code
            )

        gateway_application = web.Application(client_max_size=4096)
        gateway_application.router.add_post(
            "/v1/bot/notifications/{id}/authorize", native_api_gateway
        )
        gateway_runner, gateway_url = await start_server(gateway_application)
        from papilio_telegram.config import BotApiLimits

        api_limits = BotApiLimits(4096, 2, 1024, 5, 5)
        api = BotApi(
            gateway_url, self.settings.security.bot_service_key, 5, api_limits
        )
        bot = Bot(
            "123456:testfixture",
            session=AiohttpSession(
                api=TelegramAPIServer.from_base(telegram_url)
            ),
        )
        private_key = uuid4().hex
        settings = BotSettings(
            api_limits=api_limits,
            webhook_max_inflight=2,
            webhook_processing_timeout_seconds=2,
            webhook_max_request_bytes=4096,
            notification_delivery_enabled=True,
            notification_delivery_key=private_key,
            notification_send_timeout_seconds=5,
            notification_lease_margin_seconds=5,
            notification_max_request_bytes=4096,
            telegram_token="123456:testfixture",
            webhook_secret=uuid4().hex,
            webhook_public_url=None,
            api_url=gateway_url,
            api_key=self.settings.security.bot_service_key,
            api_timeout_seconds=5,
            listen_host="127.0.0.1",
            listen_port=0,
        )
        bridge_application = web.Application(
            client_max_size=settings.notification_max_request_bytes
        )
        register_delivery(bridge_application, bot, api, settings)
        bridge_runner, bridge_url = await start_server(bridge_application)
        config = self.settings.notifications.model_dump()
        config.update(
            outbound_enabled=True,
            endpoint=bridge_url + "/internal/notifications/deliver",
            delivery_key=private_key,
            allow_loopback_http=True,
        )
        self.settings.notifications = NotificationSettings.model_validate(
            config
        )
        try:
            await self.notification_policy(
                channel_mode="both",
                delivery_enabled=True,
                retry_seconds=1,
                max_retry_seconds=10,
                max_attempts=2,
            )
            row, _ = await self.manual_notice(customer_id)
            async with aiohttp.ClientSession() as http:
                async with http.post(
                    config["endpoint"],
                    headers={"X-Papilio-Delivery-Key": "wrong-key"},
                    json={
                        "notification_id": row["id"],
                        "claim_token": "0" * 64,
                    },
                ) as denied:
                    self.assertEqual(denied.status, 401)
            self.assertEqual(telegram_calls, [])
            self.assertTrue(await self.deliver(row["id"]))
            self.assertEqual(
                (await self.get(f"/v1/admin/notifications/{row['id']}"))[
                    "data"
                ]["status"],
                "delivered",
            )
            self.assertEqual(len(telegram_calls), 1)
            self.assertNotIn("parse_mode", telegram_calls[0])
            self.assertFalse(await self.deliver(row["id"]))
            self.assertEqual(len(telegram_calls), 1)
            telegram_mode["value"] = "rate_limit"
            limited, _ = await self.manual_notice(customer_id)
            self.assertTrue(await self.deliver(limited["id"]))
            limited = (
                await self.get(f"/v1/admin/notifications/{limited['id']}")
            )["data"]
            self.assertEqual(limited["status"], "retry")
            self.assertEqual(limited["error_code"], "telegram_retry_after")
            limited = await self.recover_notice(limited)
            telegram_mode["value"] = "forbidden"
            self.assertTrue(await self.deliver(limited["id"]))
            failed = (
                await self.get(f"/v1/admin/notifications/{limited['id']}")
            )["data"]
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(
                failed["error_code"], "telegram_recipient_forbidden"
            )
            self.assertEqual(failed["attempts"], 2)
            self.assertEqual(len(telegram_calls), 3)
        finally:
            await bridge_runner.cleanup()
            await api.close()
            await bot.session.close()
            await asyncio.gather(
                gateway_runner.cleanup(),
                telegram_runner.cleanup(),
                client.aclose(),
            )

    async def test_policy_capacities_pause_retry_modes_and_terminal_recovery(
        self,
    ):
        client, _, customer_id = await self.account()
        response_mode = {"value": "retryable", "retry_after_seconds": 0}

        async def receive(request):
            data = await request.json()
            self.assertTrue(
                (
                    await self.authorize(
                        data["notification_id"], data["claim_token"]
                    )
                )["allowed"]
            )
            return web.json_response(
                {
                    "outcome": response_mode["value"],
                    "error_code": "controlled_outcome",
                    "retry_after_seconds": response_mode[
                        "retry_after_seconds"
                    ],
                }
            )

        runner = await self.adapter(receive)
        try:
            await self.notification_policy(
                channel_mode="both",
                delivery_enabled=True,
                backoff_mode="fixed",
                retry_seconds=30,
                max_retry_seconds=60,
                max_attempts=1,
            )
            exhausted, _ = await self.manual_notice(customer_id)
            self.assertTrue(await self.deliver(exhausted["id"]))
            exhausted = (
                await self.get(f"/v1/admin/notifications/{exhausted['id']}")
            )["data"]
            self.assertEqual(exhausted["status"], "failed")
            self.assertEqual(exhausted["retry_budget_used"], 1)
            self.assertFalse(await self.deliver(exhausted["id"]))
            await self.notification_policy(
                max_attempts=3, ambiguous_mode="retry"
            )
            response_mode["value"] = "ambiguous"
            uncertain, _ = await self.manual_notice(customer_id)
            self.assertTrue(await self.deliver(uncertain["id"]))
            uncertain = (
                await self.get(f"/v1/admin/notifications/{uncertain['id']}")
            )["data"]
            self.assertEqual(uncertain["status"], "retry")
            self.assertFalse(await self.deliver(uncertain["id"]))
            response_mode["value"] = "retryable"
            response_mode["retry_after_seconds"] = 61
            oversized, _ = await self.manual_notice(customer_id)
            self.assertTrue(await self.deliver(oversized["id"]))
            oversized = (
                await self.get(f"/v1/admin/notifications/{oversized['id']}")
            )["data"]
            self.assertEqual(oversized["status"], "failed")
            self.assertEqual(
                oversized["error_code"], "notification_retry_after_capacity"
            )
            paused, _ = await self.manual_notice(customer_id)
            before = self.settings.notifications
            raw = before.model_dump()
            raw["max_attempts"] = 1
            raw["policy"]["max_attempts"] = 1
            self.settings.notifications = NotificationSettings.model_validate(
                raw
            )
            self.assertFalse(
                (await self.get("/v1/admin/notifications/policy"))["data"][
                    "capacity_valid"
                ]
            )
            self.assertIsNone(await self.claim(paused["id"]))
            self.settings.notifications = before
            await self.notification_policy(delivery_enabled=False)
            self.assertIsNone(await self.claim(paused["id"]))
            policy = (await self.get("/v1/admin/settings"))["data"]
            policy["values"]["notifications"]["max_attempts"] = (
                before.max_attempts + 1
            )
            invalid = await self.client.put(
                "/v1/admin/settings",
                headers=self.headers,
                json={
                    "expected_revision": policy["revision"],
                    "values": policy["values"],
                },
            )
            self.assertEqual(invalid.status_code, 400)
            inherited_data = {
                "customer_id": customer_id,
                "request_key": uuid4().hex,
            }
            inherited = await self.post(
                "/v1/admin/notifications", inherited_data
            )
            defaults = (await self.get("/v1/admin/settings"))["data"][
                "values"
            ]["notifications"]["templates"]["manual"]
            self.assertEqual(inherited["title"], defaults["title"])
            self.assertEqual(inherited["body"], defaults["body"])
            partial = await self.client.post(
                "/v1/admin/notifications",
                headers=self.headers,
                json={
                    "customer_id": customer_id,
                    "request_key": uuid4().hex,
                    "title": "عنوان تنها",
                },
            )
            self.assertEqual(partial.status_code, 422)
            await self.notification_policy(enabled=False)
            replay = await self.post("/v1/admin/notifications", inherited_data)
            self.assertEqual(replay["id"], inherited["id"])
            disabled = await self.client.post(
                "/v1/admin/notifications",
                headers=self.headers,
                json={
                    "customer_id": customer_id,
                    "request_key": uuid4().hex,
                    "title": "عنوان",
                    "body": "پیام تازه",
                },
            )
            self.assertEqual(disabled.status_code, 400)
            cancelled = await self.recover_notice(paused, "cancel")
            self.assertEqual(cancelled["status"], "cancelled")
            templates = (await self.get("/v1/admin/settings"))["data"][
                "values"
            ]["notifications"]["templates"]
            templates["manual"]["title"] = "{id.__class__}"
            prefs = (await self.get("/v1/admin/settings"))["data"]
            prefs["values"]["notifications"]["templates"] = templates
            unsafe = await self.client.put(
                "/v1/admin/settings",
                headers=self.headers,
                json={
                    "expected_revision": prefs["revision"],
                    "values": prefs["values"],
                },
            )
            self.assertEqual(unsafe.status_code, 422)
        finally:
            await runner.cleanup()
            await client.aclose()

    async def test_populated_support_and_sessions_survive_notification_upgrade(
        self,
    ):
        import json
        import os

        from alembic import command
        from alembic.config import Config
        from sqlalchemy.engine import make_url

        from src.modules.operations.preferences.infra.tables import (
            PreferencesRevisionTable,
        )

        assert self.settings.db is not None
        client, _, customer_id = await self.account()
        try:
            ticket = await self.post(
                "/v1/admin/support",
                {
                    "customer_id": customer_id,
                    "request_key": uuid4().hex,
                    "subject": "تیکت قبلی",
                    "body": "پیام محفوظ قبلی",
                },
            )
            preferences = (await self.get("/v1/admin/settings"))["data"]
            written = await self.client.put(
                "/v1/admin/settings",
                headers=self.headers,
                json={
                    "expected_revision": preferences["revision"],
                    "values": preferences["values"],
                },
            )
            self.assertEqual(written.status_code, 200)
            revision = written.json()["data"]["revision"]
            preferences["values"].pop("notifications")
            async with self.connection.uow() as unit:
                async with transaction(unit):
                    await unit.execute(
                        update(PreferencesRevisionTable)
                        .where(PreferencesRevisionTable.revision == revision)
                        .values(values_json=json.dumps(preferences["values"]))
                    )
                before = tuple(
                    (
                        await unit.execute(
                            text(
                                "SELECT (SELECT COUNT(*) FROM tbl_customers), "
                                "(SELECT COUNT(*) FROM tbl_support_tickets), "
                                "(SELECT COUNT(*) FROM tbl_support_messages), "
                                "(SELECT COUNT(*) FROM "
                                "tbl_customer_sessions), "
                                "(SELECT COUNT(*) FROM tbl_staff_sessions)"
                            )
                        )
                    ).one()
                )
            migration = Config("alembic.ini")
            migration.set_main_option(
                "sqlalchemy.url",
                make_url(str(self.settings.db.dsn)).render_as_string(
                    hide_password=False
                ),
            )
            with patch.dict(
                os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
            ):
                await asyncio.to_thread(
                    command.downgrade, migration, "0028_support_tickets"
                )
                await asyncio.to_thread(command.upgrade, migration, "head")
            self.assertEqual(
                (await self.client.get("/v1/admin/auth/me")).status_code, 200
            )
            self.assertEqual(
                (await client.get("/v1/customer/auth/me")).status_code, 200
            )
            messages = await client.get(
                f"/v1/customer/support/{ticket['id']}/messages"
            )
            self.assertEqual(messages.status_code, 200)
            self.assertEqual(
                messages.json()["data"][0]["body"], "پیام محفوظ قبلی"
            )
            self.assertEqual(
                (await self.get("/v1/admin/notifications"))["data"], []
            )
            self.assertTrue(
                (await self.get("/v1/admin/notifications/policy"))["data"][
                    "capacity_valid"
                ]
            )
            async with self.connection.uow() as unit:
                after = tuple(
                    (
                        await unit.execute(
                            text(
                                "SELECT (SELECT COUNT(*) FROM tbl_customers), "
                                "(SELECT COUNT(*) FROM tbl_support_tickets), "
                                "(SELECT COUNT(*) FROM tbl_support_messages), "
                                "(SELECT COUNT(*) FROM "
                                "tbl_customer_sessions), "
                                "(SELECT COUNT(*) FROM tbl_staff_sessions)"
                            )
                        )
                    ).one()
                )
                self.assertEqual(before, after)
                self.assertEqual(
                    (
                        await unit.execute(
                            text("SELECT version_num FROM alembic_version")
                        )
                    ).scalar_one(),
                    "0029_notifications",
                )
        finally:
            await client.aclose()
