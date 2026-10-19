import asyncio
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowFixture,
)


class CheckoutWorkflowFixture(StaffAdministrationWorkflowFixture):
    async def enable_manual_checkout(self, default_expiry_seconds=3600):
        from uuid import uuid4

        import httpx
        from papilio.api.application import create_app
        from papilio_tasks.apps.lifecycle import Producers
        from papilio_tasks.apps.schedulers.redis import create_app as tasks_app

        from src.config.providers import (
            infrastructure_providers,
            task_providers,
        )
        from src.config.settings import PapilioSettings

        self.raw["purchase_intents"] = {
            "policy": {
                "enabled": True,
                "admission_mode": "allow_manual_profiles",
                "default_expiry_seconds": default_expiry_seconds,
            },
            "scan_cron": "* * * * *",
            "recheck_seconds": 1,
        }
        self.checkout_namespace = "papilio:test:checkout:" + uuid4().hex
        self.raw["tasks"]["scheduler"].update(
            queue_name=self.checkout_namespace + ":jobs",
            schedule_prefix=self.checkout_namespace + ":schedules",
            result_prefix=self.checkout_namespace + ":results",
        )
        self.settings = PapilioSettings.model_validate(self.raw)
        await self.client.aclose()
        await self.app.state.dishka_container.close()
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
        response = await self.client.post(
            "/v1/admin/auth/login",
            headers={"Origin": self.settings.public.admin_origin},
            json={"username": self.username, "password": self.password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.headers = {
            "Origin": self.settings.public.admin_origin,
            "X-CSRF-Token": response.json()["csrf_token"],
        }

    async def asyncTearDown(self):
        from redis.asyncio import Redis

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

    async def pending_intent(self, suffix="funding", destination_id=None):
        from uuid import uuid4

        telegram_id = 4100000000 + int(self.suffix[:6], 16)
        identity = {
            "telegram_id": telegram_id,
            "display_name": "خریدار پرداخت",
        }
        headers = {"X-Papilio-Bot-Key": self.settings.security.bot_service_key}
        plan = await self.post(
            "/v1/admin/plans",
            {
                "code": suffix + "_" + self.suffix,
                "title": "پلن پرداخت",
                "quota_bytes": 1000000000,
                "duration_days": 30,
                "price_rial": 100000,
            },
        )
        active = await self.client.patch(
            f"/v1/admin/plans/{plan['id']}/active",
            headers=self.headers,
            json={"is_active": True},
        )
        self.assertEqual(active.status_code, 200, active.text)
        response = await self.client.post(
            f"/v1/bot/checkouts/offers/{plan['id']}",
            headers=headers,
            json=identity,
        )
        self.assertEqual(response.status_code, 200, response.text)
        offer = response.json()["data"]
        body = {
            **identity,
            "request_key": "funding_" + uuid4().hex,
            "plan_id": plan["id"],
            "funding_mode": "approved_topup",
            "topup_amount_rial": 120000,
            "destination_id": destination_id,
            "expected_offer_sha256": offer["offer_sha256"],
            "expected_price_rial": offer["price_rial"],
            "auto_renew": False,
            "expiry_seconds": 3600,
            "changed_offer_action": "require_confirmation",
        }
        response = await self.client.post(
            "/v1/bot/checkouts", headers=headers, json=body
        )
        self.assertEqual(response.status_code, 200, response.text)
        intent = response.json()["data"]
        self.assertEqual(intent["state"], "awaiting_funding")
        self.assertTrue(intent["expires_at"].endswith("Z"))
        self.assertIsNotNone(intent["topup_id"])
        return identity, headers, body, intent

    async def upload_checkout_sms(
        self,
        device,
        key,
        *,
        event=None,
        sender="OwnedBank",
        timestamp=None,
        message="واریز ۱۲۰٬۰۰۰ ریال پیگیری ۱۲۳۴۵۶۷۸",
        sent_at=None,
    ):
        payload = {
            "event_id": event or "phone_" + self.suffix,
            "sender": sender,
            "message": message,
            "sent_at": sent_at
            or datetime.now(UTC).replace(microsecond=0).isoformat(),
        }
        raw = json.dumps(payload).encode()
        timestamp = timestamp or str(int(time.time()))
        signature = hmac.new(
            key.encode(),
            f"{device}.{timestamp}.".encode() + raw,
            hashlib.sha256,
        ).hexdigest()
        result = await self.client.post(
            f"/v1/webhooks/sms-devices/{device}",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Papilio-Timestamp": timestamp,
                "X-Papilio-Signature": signature,
            },
        )
        return result

    async def ready_bundle(self):
        node = await self.post(
            "/v1/admin/network/nodes",
            {
                "code": "checkout_" + self.suffix,
                "label": "Checkout node",
                "public_host": "checkout.example.invalid",
                "public_port": 443,
                "protocol": "vless_reality",
            },
        )
        enabled = await self.client.patch(
            f"/v1/admin/network/nodes/{node['node']['id']}/enabled",
            headers=self.headers,
            json={"enabled": True},
        )
        self.assertEqual(enabled.status_code, 200)
        configuration = await self.post(
            "/v1/admin/network/configurations",
            {
                "node_id": node["node"]["id"],
                "label": "Checkout inbound",
                "options": {
                    "protocol": "vless_reality",
                    "listen_address": "0.0.0.0",
                    "server_name": "example.com",
                    "target_port": 443,
                },
            },
        )
        host = await self.post(
            f"/v1/admin/network/configurations/{configuration['id']}/hosts",
            {
                "label": "Checkout host",
                "address": "checkout.example.invalid",
                "port": 443,
                "is_enabled": True,
            },
        )
        group = await self.post(
            "/v1/admin/network/host-groups",
            {
                "code": "checkout_" + self.suffix,
                "title": "Checkout bundle",
                "is_enabled": True,
            },
        )
        membership = await self.client.put(
            f"/v1/admin/network/host-groups/{group['id']}/hosts/{host['id']}",
            headers=self.headers,
            json={"is_enabled": True, "sort_order": 0},
        )
        self.assertEqual(membership.status_code, 200, membership.text)
        plan = await self.post(
            "/v1/admin/plans",
            {
                "code": "ready_" + self.suffix,
                "title": "Ready bundle",
                "group_id": group["id"],
                "quota_bytes": 1000000000,
                "duration_days": 30,
                "price_rial": 100000,
            },
        )
        active = await self.client.patch(
            f"/v1/admin/plans/{plan['id']}/active",
            headers=self.headers,
            json={"is_active": True},
        )
        self.assertEqual(active.status_code, 200)
        customer = await self.post(
            "/v1/admin/customers", {"display_name": "Current-read buyer"}
        )
        return node["node"], customer, plan


class CheckoutWorkflowTest(CheckoutWorkflowFixture):
    async def test_populated_0048_upgrade_disabled_api_and_policy_guard(self):
        customer, subscription = await self.paid_subscription()
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", self.raw["db"]["dsn"])
        await asyncio.to_thread(
            command.downgrade, cfg, "0048_core_usage_proof"
        )
        tables = (
            "tbl_staff",
            "tbl_wallets",
            "tbl_wallet_entries",
            "tbl_topups",
            "tbl_subscriptions",
            "tbl_notifications",
        )

        async def snapshot(table):
            async with self.connection.uow() as independent:
                result = await independent.execute(
                    text(f"SELECT * FROM {table} ORDER BY id")
                )
                rows = [tuple(row) for row in result.all()]
            digest = await asyncio.to_thread(
                lambda: hashlib.sha256(
                    json.dumps(rows, default=str).encode()
                ).hexdigest()
            )
            return len(rows), digest

        before = await asyncio.gather(*(snapshot(table) for table in tables))
        self.assertTrue(all(count > 0 for count, _ in before))
        await asyncio.to_thread(command.upgrade, cfg, "0049_durable_checkout")
        after = await asyncio.gather(*(snapshot(table) for table in tables))
        self.assertEqual(before, after)
        response = await self.client.post(
            f"/v1/bot/checkouts/offers/{subscription['plan_id']}",
            headers={
                "X-Papilio-Bot-Key": self.settings.security.bot_service_key
            },
            json={"telegram_id": 8800001, "display_name": "Checkout fixture"},
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("checkout_disabled", response.text)
        prefs = (await self.get("/v1/admin/settings"))["data"]
        prefs["values"]["purchase_checkout"] = {
            "enabled": False,
            "admission_mode": "allow_manual_profiles",
            "default_expiry_seconds": 3600,
        }
        saved = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": prefs["revision"],
                "values": prefs["values"],
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        protected = await snapshot("tbl_preferences_revisions")
        with self.assertRaisesRegex(RuntimeError, "saved checkout policy"):
            await asyncio.to_thread(
                command.downgrade, cfg, "0048_core_usage_proof"
            )
        self.assertEqual(
            protected, await snapshot("tbl_preferences_revisions")
        )
        self.assertEqual(
            before,
            await asyncio.gather(*(snapshot(table) for table in tables)),
        )
        async with self.connection.uow() as independent:
            result = await independent.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema=DATABASE() AND table_name IN "
                    "('tbl_checkout_intents','tbl_checkout_action_receipts')"
                )
            )
            self.assertEqual(result.scalar_one(), 2)

    async def test_linked_financial_intent_and_action_downgrade_guard(self):
        from papilio.infra.db.transaction import transaction

        from src.modules.sales.checkout.domain.models import (
            CheckoutActionReceiptModel,
            CheckoutIntentModel,
        )
        from src.modules.sales.checkout.infra.mysql import (
            CheckoutActionReceiptRepository,
            CheckoutIntentRepository,
        )

        customer, subscription = await self.paid_subscription()
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", self.raw["db"]["dsn"])
        async with self.connection.uow() as unit:
            async with transaction():
                result = await unit.execute(
                    text(
                        "SELECT id FROM tbl_topups WHERE customer_id=:customer"
                    ),
                    {"customer": customer["id"]},
                )
                topup_id = result.scalar_one()
                result = await unit.execute(text("SELECT UTC_TIMESTAMP()"))
                created = result.scalar_one()
                intent = await CheckoutIntentRepository(unit).create(
                    CheckoutIntentModel(
                        customer_id=customer["id"],
                        request_key="migration:" + self.suffix,
                        purchase_key="migration:" + self.suffix,
                        body_sha256="a" * 64,
                        offer_sha256="b" * 64,
                        plan_id=subscription["plan_id"],
                        state="purchased",
                        funding_mode="approved_topup",
                        delivery_mode="manual_profiles",
                        price_rial=100000,
                        auto_renew=False,
                        expires_at=created,
                        changed_offer_action="require_confirmation",
                        topup_id=topup_id,
                        subscription_id=subscription["id"],
                    )
                )
                receipt = await CheckoutActionReceiptRepository(unit).create(
                    CheckoutActionReceiptModel(
                        intent_id=intent.id,
                        customer_id=customer["id"],
                        request_key="migration-action:" + self.suffix,
                        action="reconfirm",
                        body_sha256="c" * 64,
                        accepted_revision=1,
                    )
                )
        with self.assertRaisesRegex(RuntimeError, "durable checkout intent"):
            await asyncio.to_thread(
                command.downgrade, cfg, "0048_core_usage_proof"
            )
        async with self.connection.uow() as unit:
            result = await unit.execute(
                text(
                    "SELECT topup_id,subscription_id,purchase_key FROM "
                    "tbl_checkout_intents WHERE id=:id"
                ),
                {"id": intent.id},
            )
            row = result.one()
            self.assertEqual(
                tuple(row),
                (
                    topup_id,
                    subscription["id"],
                    "migration:" + self.suffix,
                ),
            )
            result = await unit.execute(
                text(
                    "SELECT intent_id,body_sha256 "
                    "FROM tbl_checkout_action_receipts "
                    "WHERE id=:id"
                ),
                {"id": receipt.id},
            )
            self.assertEqual(tuple(result.one()), (intent.id, "c" * 64))

    async def test_manual_wallet_native_worker_replay_and_identity(
        self,
    ):
        from uuid import uuid4

        import httpx

        from tests.scheduler_runtime import _exercise_native_runtime

        await self.enable_manual_checkout()
        telegram_id = 3100000000 + int(self.suffix[:6], 16)
        identity = {"telegram_id": telegram_id, "display_name": "خریدار آزمون"}
        bot_headers = {
            "X-Papilio-Bot-Key": self.settings.security.bot_service_key
        }
        home = await self.client.post(
            "/v1/bot/home", headers=bot_headers, json=identity
        )
        self.assertEqual(home.status_code, 200, home.text)
        customer_id = home.json()["data"]["customer_id"]
        plan = await self.post(
            "/v1/admin/plans",
            {
                "code": "intent_" + self.suffix,
                "title": "پلن دستی",
                "quota_bytes": 1000000000,
                "duration_days": 30,
                "price_rial": 100000,
            },
        )
        activated = await self.client.patch(
            f"/v1/admin/plans/{plan['id']}/active",
            headers=self.headers,
            json={"is_active": True},
        )
        self.assertEqual(activated.status_code, 200)
        topup = await self.post(
            "/v1/admin/payments/topups",
            {
                "customer_id": customer_id,
                "amount_rial": 300000,
            },
        )
        await self.post(
            f"/v1/admin/payments/topups/{topup['id']}/approve",
            {
                "expected_revision": 1,
                "bank_reference": "intent_" + self.suffix,
            },
        )
        offer = await self.client.post(
            f"/v1/bot/checkouts/offers/{plan['id']}",
            headers=bot_headers,
            json=identity,
        )
        self.assertEqual(offer.status_code, 200, offer.text)
        terms = offer.json()["data"]
        self.assertEqual(terms["delivery_mode"], "manual_profiles")
        body = {
            "request_key": "intent_" + uuid4().hex,
            "plan_id": plan["id"],
            "funding_mode": "wallet_only",
            "expected_offer_sha256": terms["offer_sha256"],
            "expected_price_rial": terms["price_rial"],
            "auto_renew": True,
            "expiry_seconds": 3600,
            "changed_offer_action": "require_confirmation",
            "payer_id": 987654321,
            "customer_id": 987654321,
        }
        created = await self.client.post(
            "/v1/bot/checkouts",
            headers=bot_headers,
            json={**identity, **body},
        )
        self.assertEqual(created.status_code, 200, created.text)
        intent = created.json()["data"]
        self.assertTrue(intent["expires_at"].endswith("Z"))
        self.assertEqual(intent["customer_id"], customer_id)
        self.assertEqual(intent["state"], "ready")
        self.assertIsNone(intent["subscription_id"])
        link = await self.client.post(
            "/v1/bot/account-link",
            headers=bot_headers,
            json=identity,
        )
        self.assertEqual(link.status_code, 200, link.text)
        token = link.json()["data"]["url"].rsplit("#", 1)[-1]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url=self.settings.public.customer_portal_origin,
        ) as customer:
            login = await customer.post(
                "/v1/customer/auth/exchange",
                headers={
                    "Origin": self.settings.public.customer_portal_origin,
                },
                json={"token": token},
            )
            self.assertEqual(login.status_code, 200, login.text)
            own_headers = {
                "Origin": self.settings.public.customer_portal_origin,
                "X-CSRF-Token": login.json()["csrf_token"],
            }
            replay = await customer.post(
                "/v1/customer/checkouts", headers=own_headers, json=body
            )
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertEqual(replay.json()["data"]["id"], intent["id"])
            conflict = await customer.post(
                "/v1/customer/checkouts",
                headers=own_headers,
                json={**body, "auto_renew": False},
            )
            self.assertEqual(conflict.status_code, 409, conflict.text)
            self.assertIn("checkout_request_conflict", conflict.text)
        foreign = await self.client.post(
            f"/v1/bot/checkouts/{intent['id']}/status",
            headers=bot_headers,
            json={"telegram_id": telegram_id + 1, "display_name": "دیگری"},
        )
        self.assertEqual(foreign.status_code, 404, foreign.text)
        result = await asyncio.to_thread(
            _exercise_native_runtime,
            self.raw,
            "SELECT i.state,s.status,r.state provision_state,"
            "w.balance_rial,COUNT(e.id) debit_count "
            "FROM tbl_checkout_intents i JOIN tbl_subscriptions s "
            "ON s.id=i.subscription_id "
            "JOIN tbl_provision_requests r ON r.subscription_id=s.id "
            "JOIN tbl_wallets w ON w.customer_id=i.customer_id "
            "JOIN tbl_wallet_entries e ON e.wallet_id=w.id "
            "AND e.reason='purchase' "
            "WHERE i.id=%s GROUP BY i.state,s.status,r.state,w.balance_rial",
            (intent["id"],),
            lambda row: (
                row["state"] == "purchased"
                and row["debit_count"] == 1
                and row["provision_state"] == "awaiting_profiles"
            ),
            (
                "state",
                "status",
                "provision_state",
                "balance_rial",
                "debit_count",
            ),
            ("ScanCheckouts", "RecoverCheckout", "PrepareProvision"),
        )
        self.assertEqual(
            result,
            ("purchased", "pending_provision", "awaiting_profiles", 200000, 1),
        )
        status = await self.client.post(
            f"/v1/bot/checkouts/{intent['id']}/status",
            headers=bot_headers,
            json=identity,
        )
        self.assertEqual(status.status_code, 200, status.text)
        self.assertIsNotNone(status.json()["data"]["subscription_id"])
        self.assertTrue(status.json()["data"]["expires_at"].endswith("Z"))
        replay = await self.client.post(
            "/v1/bot/checkouts",
            headers=bot_headers,
            json={**identity, **body},
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(
            replay.json()["data"]["subscription_id"],
            status.json()["data"]["subscription_id"],
        )

    async def test_manual_approval_same_queue_native_purchase_once(self):
        from redis.asyncio import Redis

        from tests.scheduler_runtime import _exercise_native_runtime

        await self.enable_manual_checkout()
        identity, headers, body, intent = await self.pending_intent()
        redis = Redis.from_url(self.raw["redis"]["url"])
        try:
            before = await redis.xlen(self.checkout_namespace + ":jobs")
            self.assertEqual(before, 1)
            approved = await self.post(
                f"/v1/admin/payments/topups/{intent['topup_id']}/approve",
                {
                    "expected_revision": 1,
                    "bank_reference": "same_queue_" + self.suffix,
                },
            )
            self.assertEqual(approved["status"], "approved")
            self.assertEqual(
                await redis.xlen(self.checkout_namespace + ":jobs"), before + 1
            )
            await self.post(
                f"/v1/admin/payments/topups/{intent['topup_id']}/approve",
                {
                    "expected_revision": 1,
                    "bank_reference": "same_queue_" + self.suffix,
                },
            )
            self.assertEqual(
                await redis.xlen(self.checkout_namespace + ":jobs"), before + 2
            )
        finally:
            await redis.aclose()
        outcome = await asyncio.to_thread(
            _exercise_native_runtime,
            self.raw,
            "SELECT i.state,r.state provision_state,w.balance_rial,"
            "SUM(e.reason='purchase') debits,"
            "SUM(e.reason='approved_topup') credits "
            "FROM tbl_checkout_intents i JOIN tbl_subscriptions s "
            "ON s.id=i.subscription_id JOIN tbl_provision_requests r "
            "ON r.subscription_id=s.id JOIN tbl_wallets w "
            "ON w.customer_id=i.customer_id "
            "JOIN tbl_wallet_entries e ON e.wallet_id=w.id WHERE i.id=%s "
            "GROUP BY i.state,r.state,w.balance_rial",
            (intent["id"],),
            lambda row: (
                row["state"] == "purchased"
                and row["provision_state"] == "awaiting_profiles"
            ),
            ("state", "provision_state", "balance_rial", "debits", "credits"),
            ("RecoverCheckout", "ScanCheckouts", "PrepareProvision"),
            owned_namespace=self.checkout_namespace,
        )
        self.assertEqual(
            outcome, ("purchased", "awaiting_profiles", 20000, 1, 1)
        )
        replay = await self.client.post(
            "/v1/bot/checkouts", headers=headers, json=body
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["data"]["state"], "purchased")
        self.assertIsNotNone(replay.json()["data"]["subscription_id"])

    async def test_enrolled_sms_ambiguous_then_same_queue_purchase_once(self):
        from datetime import UTC, datetime, timedelta

        from redis.asyncio import Redis

        from tests.scheduler_runtime import _exercise_native_runtime

        await self.enable_manual_checkout()
        destination = await self.post(
            "/v1/admin/payments/destinations",
            {
                "title": "Checkout bank",
                "kind": "card",
                "account": "6037990000000001",
                "recipient": "Fixture recipient",
                "bank_name": "Owned bank",
                "is_active": True,
            },
        )
        device_body = {
            "label": "Checkout phone",
            "senders": ["OwnedBank"],
            "is_active": True,
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "approval_mode": "unique_sms",
            "destination_id": destination["destination_id"],
        }
        first = await self.post("/v1/admin/payments/sms-devices", device_body)
        _, headers, _, intent = await self.pending_intent(
            "sms", destination["destination_id"]
        )
        other_customer = await self.post(
            "/v1/admin/customers", {"display_name": "Ambiguous customer"}
        )
        other_topup = await self.post(
            "/v1/admin/payments/topups",
            {
                "customer_id": other_customer["id"],
                "amount_rial": 120000,
                "destination_id": destination["destination_id"],
            },
        )
        sent_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        event_id = "checkout_sms_" + self.suffix
        redis = Redis.from_url(self.raw["redis"]["url"])
        try:
            rejected = await self.upload_checkout_sms(
                first["device"]["id"],
                "incorrect-key",
                event=event_id,
                sent_at=sent_at,
            )
            self.assertEqual(rejected.status_code, 401)
            ambiguous = await self.upload_checkout_sms(
                first["device"]["id"],
                first["api_key"],
                event=event_id,
                sent_at=sent_at,
            )
            self.assertEqual(ambiguous.status_code, 200, ambiguous.text)
            self.assertEqual(ambiguous.json(), {"accepted": True})
            self.assertEqual(
                await redis.xlen(self.checkout_namespace + ":jobs"), 1
            )
            pending = (
                await self.get(
                    f"/v1/admin/payments/topups/{intent['topup_id']}"
                )
            )["data"]
            self.assertEqual(pending["status"], "pending")
            await self.post(
                f"/v1/admin/payments/topups/{other_topup['id']}/reject",
                {"expected_revision": 1},
            )
            accepted = await self.upload_checkout_sms(
                first["device"]["id"],
                first["api_key"],
                event=event_id,
                sent_at=sent_at,
            )
            self.assertEqual(accepted.status_code, 200, accepted.text)
            self.assertEqual(accepted.json(), {"accepted": True})
            self.assertEqual(
                await redis.xlen(self.checkout_namespace + ":jobs"), 2
            )
            replay = await self.upload_checkout_sms(
                first["device"]["id"],
                first["api_key"],
                event=event_id,
                sent_at=sent_at,
            )
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertEqual(
                await redis.xlen(self.checkout_namespace + ":jobs"), 3
            )
            second = await self.post(
                "/v1/admin/payments/sms-devices",
                {**device_body, "label": "Second phone"},
            )
            duplicate = await self.upload_checkout_sms(
                second["device"]["id"],
                second["api_key"],
                event=event_id + "_copy",
                sent_at=sent_at,
            )
            self.assertEqual(duplicate.status_code, 200, duplicate.text)
            self.assertEqual(duplicate.json(), {"accepted": True})
            self.assertEqual(
                await redis.xlen(self.checkout_namespace + ":jobs"), 3
            )
        finally:
            await redis.aclose()
        outcome = await asyncio.to_thread(
            _exercise_native_runtime,
            self.raw,
            "SELECT i.state,r.state provision_state,w.balance_rial,"
            "SUM(e.reason='purchase') debits,"
            "SUM(e.reason='approved_topup') credits "
            "FROM tbl_checkout_intents i JOIN tbl_subscriptions s "
            "ON s.id=i.subscription_id "
            "JOIN tbl_provision_requests r ON r.subscription_id=s.id "
            "JOIN tbl_wallets w ON w.customer_id=i.customer_id "
            "JOIN tbl_wallet_entries e ON e.wallet_id=w.id WHERE i.id=%s "
            "GROUP BY i.state,r.state,w.balance_rial",
            (intent["id"],),
            lambda row: (
                row["state"] == "purchased"
                and row["provision_state"] == "awaiting_profiles"
            ),
            ("state", "provision_state", "balance_rial", "debits", "credits"),
            ("RecoverCheckout", "ScanCheckouts", "PrepareProvision"),
            owned_namespace=self.checkout_namespace,
        )
        self.assertEqual(
            outcome, ("purchased", "awaiting_profiles", 20000, 1, 1)
        )
        approved = (
            await self.get(f"/v1/admin/payments/topups/{intent['topup_id']}")
        )["data"]
        self.assertEqual(
            approved["approved_by_device_id"], first["device"]["id"]
        )
        self.assertIsNotNone(approved["approved_by_sms_id"])
        self.assertIsNone(approved["approved_by_staff_id"])

    async def test_cancel_expiry_late_approval_keeps_wallet_without_purchase(
        self,
    ):
        from datetime import timedelta

        from papilio.infra.db.transaction import transaction

        from tests.scheduler_runtime import _exercise_native_runtime

        await self.enable_manual_checkout()
        identity, headers, _, cancelled = await self.pending_intent("cancel")
        _, _, _, expired = await self.pending_intent("expire")
        cancel_body = {
            **identity,
            "request_key": "cancel_" + self.suffix,
            "expected_revision": cancelled["revision"],
        }
        response = await self.client.post(
            f"/v1/bot/checkouts/{cancelled['id']}/cancel",
            headers=headers,
            json=cancel_body,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"]["state"], "cancelled")
        self.assertTrue(response.json()["data"]["expires_at"].endswith("Z"))
        replay = await self.client.post(
            f"/v1/bot/checkouts/{cancelled['id']}/cancel",
            headers=headers,
            json=cancel_body,
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(
            response.json()["data"]["revision"],
            replay.json()["data"]["revision"],
        )
        async with self.connection.uow() as unit:
            async with transaction():
                await unit.execute(
                    text(
                        "UPDATE tbl_checkout_intents SET expires_at=:expiry "
                        "WHERE id=:id"
                    ),
                    {
                        "id": expired["id"],
                        "expiry": (
                            datetime.now(UTC) - timedelta(seconds=1)
                        ).replace(tzinfo=None),
                    },
                )
        approved = await self.post(
            f"/v1/admin/payments/topups/{cancelled['topup_id']}/approve",
            {
                "expected_revision": 1,
                "bank_reference": "cancel_" + self.suffix,
            },
        )
        self.assertEqual(approved["status"], "approved")
        approved = await self.post(
            f"/v1/admin/payments/topups/{expired['topup_id']}/approve",
            {
                "expected_revision": 1,
                "bank_reference": "expire_" + self.suffix,
            },
        )
        self.assertEqual(approved["status"], "approved")
        outcome = await asyncio.to_thread(
            _exercise_native_runtime,
            self.raw,
            "SELECT SUM(i.state='cancelled') cancelled,"
            "SUM(i.state='expired') expired,"
            "SUM(i.subscription_id IS NOT NULL) linked,w.balance_rial "
            "FROM tbl_checkout_intents i JOIN tbl_wallets w "
            "ON w.customer_id=i.customer_id "
            "WHERE i.id IN (%s,%s) GROUP BY w.balance_rial",
            (cancelled["id"], expired["id"]),
            lambda row: row["cancelled"] == 1 and row["expired"] == 1,
            ("cancelled", "expired", "linked", "balance_rial"),
            ("RecoverCheckout", "ScanCheckouts"),
            owned_namespace=self.checkout_namespace,
        )
        self.assertEqual(outcome, (1, 1, 0, 240000))
        async with self.connection.uow() as unit:
            result = await unit.execute(
                text(
                    "SELECT SUM(reason='purchase') debits,"
                    "SUM(reason='approved_topup') credits "
                    "FROM tbl_wallet_entries e "
                    "JOIN tbl_wallets w ON w.id=e.wallet_id "
                    "WHERE w.customer_id=:id"
                ),
                {"id": cancelled["customer_id"]},
            )
            self.assertEqual(tuple(result.one()), (0, 2))
            result = await unit.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_checkout_action_receipts "
                    "WHERE intent_id=:id"
                ),
                {"id": cancelled["id"]},
            )
            self.assertEqual(result.scalar_one(), 1)

    async def test_offer_current_disabled_node_after_held_rr(self):
        from contextvars import Context

        from papilio.errors.exceptions import ConflictException
        from papilio.infra.db.transaction import transaction
        from papilio.infra.db.uow import MySQLUnitOfWork

        from src.modules.sales.checkout.interfaces import ICheckoutOfferQuery

        await self.enable_manual_checkout()
        node, customer, plan = await self.ready_bundle()
        async with self.app.state.dishka_container() as scope:
            unit = await scope.get(MySQLUnitOfWork)
            offers = await scope.get(ICheckoutOfferQuery)
            with self.assertRaises(ConflictException) as error:
                async with transaction(unit):
                    old = await unit.execute(
                        text("SELECT is_enabled FROM tbl_nodes WHERE id=:id"),
                        {"id": node["id"]},
                    )
                    self.assertTrue(old.scalar_one())
                    changed = await asyncio.create_task(
                        self.client.patch(
                            f"/v1/admin/network/nodes/{node['id']}/enabled",
                            headers=self.headers,
                            json={"enabled": False},
                        ),
                        context=Context(),
                    )
                    self.assertEqual(changed.status_code, 200, changed.text)
                    await offers.get(customer["id"], plan["id"])
            self.assertEqual(
                error.exception.message_code, "checkout_bundle_unavailable"
            )

    async def test_node_contention_rejects_purchase_without_debit(self):
        from contextvars import Context

        from papilio.errors.exceptions import ConflictException
        from papilio.infra.db.transaction import transaction

        from src.modules.sales.checkout.interfaces import ICheckoutOfferQuery
        from src.modules.sales.subscriptions.domain.dtos import (
            SubscriptionCreate,
        )
        from src.modules.sales.subscriptions.interfaces import (
            ISubscriptionCommand,
        )

        await self.enable_manual_checkout()
        node, customer, plan = await self.ready_bundle()
        topup = await self.post(
            "/v1/admin/payments/topups",
            {"customer_id": customer["id"], "amount_rial": 200000},
        )
        await self.post(
            f"/v1/admin/payments/topups/{topup['id']}/approve",
            {"expected_revision": 1, "bank_reference": "busy_" + self.suffix},
        )
        async with self.app.state.dishka_container() as scope:
            offers = await scope.get(ICheckoutOfferQuery)
            offer = await offers.get(customer["id"], plan["id"])

        async def purchase():
            async with self.app.state.dishka_container() as scope:
                command = await scope.get(ISubscriptionCommand)
                result = await command.purchase(
                    SubscriptionCreate(
                        customer_id=customer["id"],
                        plan_id=plan["id"],
                        auto_renew=False,
                        purchase_key="busy_" + self.suffix,
                        expected_price_rial=offer.price_rial,
                        expected_offer_sha256=offer.offer_sha256,
                    )
                )
                return result

        async with self.connection.uow() as holder:
            async with transaction(holder):
                await holder.execute(
                    text("SELECT id FROM tbl_nodes WHERE id=:id FOR UPDATE"),
                    {"id": node["id"]},
                )
                with self.assertRaises(ConflictException) as error:
                    await asyncio.wait_for(
                        asyncio.create_task(purchase(), context=Context()),
                        timeout=3,
                    )
                self.assertEqual(
                    error.exception.message_code, "checkout_offer_busy"
                )
        wallet = (
            await self.get(f"/v1/admin/payments/wallets/{customer['id']}")
        )["data"]
        self.assertEqual(wallet["balance_rial"], 200000)
        async with self.connection.uow() as unit:
            result = await unit.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_subscriptions "
                    "WHERE customer_id=:id"
                ),
                {"id": customer["id"]},
            )
            self.assertEqual(result.scalar_one(), 0)

    async def test_funded_attempt_reads_current_wallet_after_held_rr(self):
        from contextvars import Context

        from papilio.infra.db.transaction import transaction
        from papilio.infra.db.uow import MySQLUnitOfWork

        from src.modules.sales.checkout.interfaces import (
            ICheckoutIntentCommand,
        )

        await self.enable_manual_checkout()
        _, _, _, intent = await self.pending_intent("wallet_rr")
        extra = await self.post(
            "/v1/admin/payments/topups",
            {"customer_id": intent["customer_id"], "amount_rial": 30000},
        )
        await self.post(
            f"/v1/admin/payments/topups/{extra['id']}/approve",
            {
                "expected_revision": 1,
                "bank_reference": "old_wallet_" + self.suffix,
            },
        )
        async with self.app.state.dishka_container() as scope:
            unit = await scope.get(MySQLUnitOfWork)
            command = await scope.get(ICheckoutIntentCommand)
            async with transaction(unit):
                old = await unit.execute(
                    text(
                        "SELECT balance_rial FROM tbl_wallets "
                        "WHERE customer_id=:id"
                    ),
                    {"id": intent["customer_id"]},
                )
                self.assertEqual(old.scalar_one(), 30000)
                credited = await asyncio.create_task(
                    self.post(
                        f"/v1/admin/payments/topups/{intent['topup_id']}/approve",
                        {
                            "expected_revision": 1,
                            "bank_reference": "new_wallet_" + self.suffix,
                        },
                    ),
                    context=Context(),
                )
                self.assertEqual(credited["status"], "approved")
                purchase = await command.attempt(intent["id"])
                self.assertEqual(purchase.state, "purchased")
                self.assertIsNotNone(purchase.subscription_id)
        wallet = (
            await self.get(
                f"/v1/admin/payments/wallets/{intent['customer_id']}"
            )
        )["data"]
        self.assertEqual(wallet["balance_rial"], 50000)

    async def test_changed_offer_owned_history_lookup_and_reconfirmation(self):
        from src.modules.billing.destinations.domain.dtos import CheckoutPolicy
        from tests.scheduler_runtime import _exercise_native_runtime

        await self.enable_manual_checkout(default_expiry_seconds=7200)
        destination_body = {
            "title": "Captured account",
            "kind": "card",
            "account": "6037990000000001",
            "recipient": "Fixture recipient",
            "bank_name": "Fixture bank",
            "is_active": True,
        }
        destination = await self.post(
            "/v1/admin/payments/destinations", destination_body
        )
        identity, headers, body, intent = await self.pending_intent(
            "changed", destination["destination_id"]
        )
        funding = await self.client.post(
            "/v1/bot/checkouts/funding", headers=headers, json=identity
        )
        self.assertEqual(funding.status_code, 200, funding.text)
        expected_funding = CheckoutPolicy.model_validate(
            self.raw["checkout"]["policy"]
        )
        self.assertEqual(
            funding.json()["data"], expected_funding.model_dump(mode="json")
        )
        destinations = await self.client.post(
            "/v1/bot/checkouts/destinations?per_page=1",
            headers=headers,
            json=identity,
        )
        self.assertEqual(destinations.status_code, 200, destinations.text)
        self.assertEqual(
            destinations.json()["meta"]["pager"]["total_items"], 1
        )
        self.assertEqual(
            destinations.json()["data"][0]["destination_id"],
            destination["destination_id"],
        )
        edited = await self.client.put(
            f"/v1/admin/payments/destinations/{destination['destination_id']}",
            headers=self.headers,
            json={**destination_body, "account": "6037990000000002"},
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        live = await self.client.post(
            f"/v1/bot/checkouts/destinations/{destination['destination_id']}/instruction",
            headers=headers,
            json=identity,
        )
        self.assertEqual(live.status_code, 200, live.text)
        self.assertEqual(live.json()["data"]["account"], "6037990000000002")
        captured = await self.client.post(
            f"/v1/bot/checkouts/{intent['id']}/payment-instruction",
            headers=headers,
            json=identity,
        )
        self.assertEqual(captured.status_code, 200, captured.text)
        self.assertEqual(
            captured.json()["data"]["account"], "6037990000000001"
        )
        foreign = {**identity, "telegram_id": identity["telegram_id"] + 1}
        denied = await self.client.post(
            f"/v1/bot/checkouts/{intent['id']}/payment-instruction",
            headers=headers,
            json=foreign,
        )
        self.assertEqual(denied.status_code, 404, denied.text)
        changed = await self.client.patch(
            f"/v1/admin/plans/{intent['plan_id']}",
            headers=self.headers,
            json={"price_rial": 110000},
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        await self.post(
            f"/v1/admin/payments/topups/{intent['topup_id']}/approve",
            {
                "expected_revision": 1,
                "bank_reference": "changed_" + self.suffix,
            },
        )
        outcome = await asyncio.to_thread(
            _exercise_native_runtime,
            self.raw,
            "SELECT i.state,i.reason_code,w.balance_rial,i.subscription_id "
            "FROM tbl_checkout_intents i JOIN tbl_wallets w "
            "ON w.customer_id=i.customer_id WHERE i.id=%s",
            (intent["id"],),
            lambda row: row["state"] == "action_required",
            ("state", "reason_code", "balance_rial", "subscription_id"),
            ("ScanCheckouts", "RecoverCheckout"),
            owned_namespace=self.checkout_namespace,
        )
        self.assertEqual(
            outcome,
            ("action_required", "checkout_offer_changed", 120000, None),
        )
        history = await self.client.post(
            "/v1/bot/checkouts/history?state=action_required&per_page=1",
            headers=headers,
            json=identity,
        )
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual(history.json()["meta"]["pager"]["total_items"], 1)
        current = history.json()["data"][0]
        self.assertEqual(current["id"], intent["id"])
        self.assertTrue(current["expires_at"].endswith("Z"))
        lookup = await self.client.post(
            "/v1/bot/checkouts/lookup",
            headers=headers,
            json={**identity, "request_key": body["request_key"]},
        )
        self.assertEqual(lookup.status_code, 200, lookup.text)
        self.assertEqual(lookup.json()["data"]["id"], intent["id"])
        missing = await self.client.post(
            "/v1/bot/checkouts/lookup",
            headers=headers,
            json={**foreign, "request_key": body["request_key"]},
        )
        self.assertEqual(missing.status_code, 404, missing.text)
        other_history = await self.client.post(
            "/v1/bot/checkouts/history", headers=headers, json=foreign
        )
        self.assertEqual(other_history.status_code, 200, other_history.text)
        self.assertEqual(other_history.json()["data"], [])
        stale = await self.client.post(
            f"/v1/bot/checkouts/{intent['id']}/reconfirm",
            headers=headers,
            json={
                **identity,
                "request_key": "stale_" + self.suffix,
                "expected_revision": current["revision"],
                "expected_offer_sha256": body["expected_offer_sha256"],
                "expected_price_rial": body["expected_price_rial"],
            },
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertIn("checkout_offer_changed", stale.text)
        refreshed = await self.client.post(
            f"/v1/bot/checkouts/offers/{intent['plan_id']}",
            headers=headers,
            json=identity,
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        offer = refreshed.json()["data"]
        self.assertEqual(
            offer["default_expiry_seconds"],
            self.raw["purchase_intents"]["policy"]["default_expiry_seconds"],
        )
        reconfirm_body = {
            **identity,
            "request_key": "reconfirm_" + self.suffix,
            "expected_revision": current["revision"],
            "expected_offer_sha256": offer["offer_sha256"],
            "expected_price_rial": offer["price_rial"],
        }
        accepted = await self.client.post(
            f"/v1/bot/checkouts/{intent['id']}/reconfirm",
            headers=headers,
            json=reconfirm_body,
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        replay = await self.client.post(
            f"/v1/bot/checkouts/{intent['id']}/reconfirm",
            headers=headers,
            json=reconfirm_body,
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(
            accepted.json()["data"]["revision"],
            replay.json()["data"]["revision"],
        )
        conflict = await self.client.post(
            f"/v1/bot/checkouts/{intent['id']}/reconfirm",
            headers=headers,
            json={
                **reconfirm_body,
                "expected_revision": current["revision"] + 1,
            },
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertIn("checkout_action_request_conflict", conflict.text)
        outcome = await asyncio.to_thread(
            _exercise_native_runtime,
            self.raw,
            "SELECT i.state,r.state provision_state,w.balance_rial,"
            "SUM(e.reason='purchase') debits FROM tbl_checkout_intents i "
            "JOIN tbl_subscriptions s ON s.id=i.subscription_id "
            "JOIN tbl_provision_requests r ON r.subscription_id=s.id "
            "JOIN tbl_wallets w ON w.customer_id=i.customer_id "
            "JOIN tbl_wallet_entries e ON e.wallet_id=w.id "
            "WHERE i.id=%s GROUP BY i.state,r.state,w.balance_rial",
            (intent["id"],),
            lambda row: (
                row["state"] == "purchased"
                and row["provision_state"] == "awaiting_profiles"
            ),
            ("state", "provision_state", "balance_rial", "debits"),
            ("ScanCheckouts", "RecoverCheckout", "PrepareProvision"),
            owned_namespace=self.checkout_namespace,
        )
        self.assertEqual(outcome, ("purchased", "awaiting_profiles", 10000, 1))
        async with self.connection.uow() as unit:
            result = await unit.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_checkout_action_receipts "
                    "WHERE intent_id=:id"
                ),
                {"id": intent["id"]},
            )
            self.assertEqual(result.scalar_one(), 1)
        # Reconfirmation returns the durable accepted intent before the worker
        # links the subscription; read that actual link after fulfillment.
        status = await self.client.post(
            f"/v1/bot/checkouts/{intent['id']}/status",
            headers=headers,
            json=identity,
        )
        self.assertEqual(status.status_code, 200, status.text)
        subscription_id = status.json()["data"]["subscription_id"]
        self.assertIsNotNone(subscription_id)
        failed = await self.post(
            f"/v1/admin/subscriptions/{subscription_id}/provision-failed",
            {"reason": "Verified manual profile provisioning failure"},
        )
        self.assertEqual(failed["status"], "failed")
        repeated = await self.post(
            f"/v1/admin/subscriptions/{subscription_id}/provision-failed",
            {"reason": "Verified manual profile provisioning failure"},
        )
        self.assertEqual(repeated["status"], "failed")
        replay = await self.client.post(
            "/v1/bot/checkouts", headers=headers, json=body
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(
            replay.json()["data"]["subscription_id"], subscription_id
        )
        from src.modules.sales.checkout.interfaces import (
            ICheckoutRecoveryRunner,
        )

        async with self.app.state.dishka_container() as scope:
            runner = await scope.get(ICheckoutRecoveryRunner)
            recovered = await runner.run(intent["id"])
            self.assertEqual(recovered.state, "purchased")
            self.assertEqual(recovered.subscription_id, subscription_id)
        wallet = (
            await self.get(
                f"/v1/admin/payments/wallets/{intent['customer_id']}"
            )
        )["data"]
        self.assertEqual(wallet["balance_rial"], 120000)
        async with self.connection.uow() as unit:
            result = await unit.execute(
                text(
                    "SELECT SUM(reason='purchase'),"
                    "SUM(reason='provision_refund') "
                    "FROM tbl_wallet_entries e JOIN tbl_wallets w "
                    "ON w.id=e.wallet_id "
                    "WHERE w.customer_id=:id"
                ),
                {"id": intent["customer_id"]},
            )
            self.assertEqual(tuple(result.one()), (1, 1))
            result = await unit.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_subscriptions "
                    "WHERE customer_id=:id"
                ),
                {"id": intent["customer_id"]},
            )
            self.assertEqual(result.scalar_one(), 1)

    async def test_attempt_current_preferences_after_held_rr(self):
        from contextvars import Context

        from papilio.errors.exceptions import ConflictException
        from papilio.infra.db.transaction import transaction
        from papilio.infra.db.uow import MySQLUnitOfWork

        from src.modules.sales.checkout.interfaces import (
            ICheckoutIntentCommand,
            ICheckoutRecoveryRunner,
        )

        await self.enable_manual_checkout()
        _, headers, _, intent = await self.pending_intent("prefs_rr")
        await self.post(
            f"/v1/admin/payments/topups/{intent['topup_id']}/approve",
            {
                "expected_revision": 1,
                "bank_reference": "prefs_rr_" + self.suffix,
            },
        )
        prefs = (await self.get("/v1/admin/settings"))["data"]
        prefs["values"]["fulfillment"]["failure_action"] = "refund_wallet"
        async with self.app.state.dishka_container() as scope:
            unit = await scope.get(MySQLUnitOfWork)
            command = await scope.get(ICheckoutIntentCommand)
            with self.assertRaises(ConflictException) as error:
                async with transaction(unit):
                    await unit.execute(
                        text("SELECT COUNT(*) FROM tbl_preferences_revisions")
                    )
                    changed = await asyncio.create_task(
                        self.client.put(
                            "/v1/admin/settings",
                            headers=self.headers,
                            json={
                                "expected_revision": prefs["revision"],
                                "values": prefs["values"],
                            },
                        ),
                        context=Context(),
                    )
                    self.assertEqual(changed.status_code, 200, changed.text)
                    await command.attempt(intent["id"])
            self.assertEqual(
                error.exception.message_code, "checkout_offer_changed"
            )
        # Failed nested attempt rolled back fully. Recovery records the durable
        # outcome in a fresh native operation, never a rollback-only scope.
        async with self.app.state.dishka_container() as scope:
            runner = await scope.get(ICheckoutRecoveryRunner)
            recovered = await runner.run(intent["id"])
            self.assertEqual(recovered.state, "action_required")
            self.assertIsNone(recovered.subscription_id)
        wallet = (
            await self.get(
                f"/v1/admin/payments/wallets/{intent['customer_id']}"
            )
        )["data"]
        self.assertEqual(wallet["balance_rial"], 120000)
        history = await self.client.post(
            "/v1/bot/checkouts/history",
            headers=headers,
            json={
                "telegram_id": 4100000000 + int(self.suffix[:6], 16),
                "display_name": "خریدار",
            },
        )
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual(
            history.json()["data"][0]["reason_code"], "checkout_offer_changed"
        )
