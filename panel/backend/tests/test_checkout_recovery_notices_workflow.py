"""Native transient checkout recovery and immutable notice acceptance."""

import asyncio
from contextvars import Context

from papilio.infra.db.transaction import transaction
from sqlalchemy import text

from src.modules.sales.checkout.domain.contracts import CheckoutCreate
from src.modules.sales.checkout.interfaces import (
    ICheckoutIntentCommand,
    ICheckoutOfferQuery,
    ICheckoutRecoveryRunner,
)
from tests.scheduler_runtime import _exercise_native_runtime
from tests.test_checkout_workflow import CheckoutWorkflowTest


class CheckoutRecoveryNoticesWorkflowTest(CheckoutWorkflowTest):
    async def test_busy_funded_checkout_retries_until_expiry_native_worker(
        self,
    ):
        await self.enable_manual_checkout()
        node, customer, plan = await self.ready_bundle()
        topup = await self.post(
            "/v1/admin/payments/topups",
            {"customer_id": customer["id"], "amount_rial": 120000},
        )
        await self.post(
            f"/v1/admin/payments/topups/{topup['id']}/approve",
            {"expected_revision": 1, "bank_reference": "retry_" + self.suffix},
        )
        async with self.app.state.dishka_container() as scope:
            offers = await scope.get(ICheckoutOfferQuery)
            offer = await offers.get(customer["id"], plan["id"])
        body = CheckoutCreate(
            request_key="retry_" + self.suffix,
            plan_id=plan["id"],
            funding_mode="wallet_only",
            expected_offer_sha256=offer.offer_sha256,
            expected_price_rial=offer.price_rial,
            auto_renew=False,
            expiry_seconds=3600,
            changed_offer_action="require_confirmation",
        )
        async with self.app.state.dishka_container() as scope:
            commands = await scope.get(ICheckoutIntentCommand)
            intent = await commands.create(customer["id"], body)
            intent_id = intent.id
        # No publication is needed: the actual scheduler must discover the row.
        async with self.connection.uow() as holder:
            async with transaction(holder):
                await holder.execute(
                    text("SELECT id FROM tbl_nodes WHERE id=:id FOR UPDATE"),
                    {"id": node["id"]},
                )
                blocked = await asyncio.to_thread(
                    _exercise_native_runtime,
                    self.raw,
                    "SELECT state,reason_code,subscription_id "
                    "FROM tbl_checkout_intents WHERE id=%s",
                    (intent_id,),
                    lambda row: row["reason_code"] == "checkout_offer_busy",
                    ("state", "reason_code", "subscription_id"),
                    ("ScanCheckouts", "RecoverCheckout"),
                    owned_namespace=self.checkout_namespace,
                )
                self.assertEqual(
                    blocked, ("ready", "checkout_offer_busy", None)
                )
        recovered = await asyncio.to_thread(
            _exercise_native_runtime,
            self.raw,
            "SELECT i.state,w.balance_rial,COUNT(DISTINCT s.id) subscriptions,"
            "SUM(e.reason='purchase') debits,"
            "SUM(e.reason='approved_topup') credits "
            "FROM tbl_checkout_intents i JOIN tbl_subscriptions s "
            "ON s.id=i.subscription_id "
            "JOIN tbl_wallets w ON w.customer_id=i.customer_id "
            "JOIN tbl_wallet_entries e ON e.wallet_id=w.id WHERE i.id=%s "
            "GROUP BY i.state,w.balance_rial",
            (intent_id,),
            lambda row: row["state"] == "purchased",
            ("state", "balance_rial", "subscriptions", "debits", "credits"),
            ("ScanCheckouts", "RecoverCheckout", "PrepareProvision"),
            owned_namespace=self.checkout_namespace,
        )
        self.assertEqual(recovered, ("purchased", 20000, 1, 1, 1))
        async with self.app.state.dishka_container() as scope:
            commands = await scope.get(ICheckoutIntentCommand)
            replay = await commands.create(customer["id"], body)
            self.assertEqual(replay.id, intent_id)
            self.assertEqual(replay.offer_sha256, offer.offer_sha256)
            self.assertEqual(replay.state, "purchased")

    async def configure_checkout_notices(self):
        prefs = (await self.get("/v1/admin/settings"))["data"]
        supported = prefs["capabilities"]["supported_notification_kinds"]
        kinds = (
            "checkout_action_required",
            "checkout_cancelled",
            "checkout_expired",
        )
        self.assertTrue(set(kinds).issubset(supported))
        prefs["values"]["notifications"].update(
            enabled=True, channel_mode="inbox", delivery_enabled=False
        )
        prefs["values"]["notifications"]["templates"].update(
            {
                kind: {
                    "enabled": True,
                    "title": "Checkout {id}",
                    "body": "{status} {amount_toman}",
                }
                for kind in kinds
            }
        )
        response = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": prefs["revision"],
                "values": prefs["values"],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    async def test_distinct_cancel_keys_preserve_terminal_notice_once(self):
        await self.enable_manual_checkout()
        await self.configure_checkout_notices()
        identity, headers, _, intent = await self.pending_intent(
            "cancelnotice"
        )
        first_body = {
            **identity,
            "request_key": "first_cancel_" + self.suffix,
            "expected_revision": intent["revision"],
        }
        first = await self.client.post(
            f"/v1/bot/checkouts/{intent['id']}/cancel",
            headers=headers,
            json=first_body,
        )
        self.assertEqual(first.status_code, 200, first.text)
        first_row = first.json()["data"]
        second_body = {
            **identity,
            "request_key": "second_cancel_" + self.suffix,
            "expected_revision": first_row["revision"],
        }
        second = await self.client.post(
            f"/v1/bot/checkouts/{intent['id']}/cancel",
            headers=headers,
            json=second_body,
        )
        self.assertEqual(second.status_code, 200, second.text)
        async with self.connection.uow() as unit:
            notices = await unit.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_notifications "
                    "WHERE record_id=:id AND kind='checkout_cancelled'"
                ),
                {"id": intent["id"]},
            )
            count = notices.scalar_one()
            receipts = await unit.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_checkout_action_receipts "
                    "WHERE intent_id=:id"
                ),
                {"id": intent["id"]},
            )
            self.assertEqual(receipts.scalar_one(), 2)
        with self.subTest("same terminal revision"):
            self.assertEqual(
                second.json()["data"]["revision"], first_row["revision"]
            )
        with self.subTest("one immutable cancellation notice"):
            self.assertEqual(count, 1)
        replay = await self.client.post(
            f"/v1/bot/checkouts/{intent['id']}/cancel",
            headers=headers,
            json=second_body,
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["data"], second.json()["data"])

    async def recover_native(self, intent_id):
        async with self.app.state.dishka_container() as scope:
            runner = await scope.get(ICheckoutRecoveryRunner)
            result = await runner.run(intent_id)
            return result

    async def test_manual_conflict_deadline_and_true_offer_changes(self):
        await self.enable_manual_checkout()
        prefs = await self.configure_checkout_notices()
        prefs["values"]["purchase_checkout"] = {
            "enabled": True,
            "admission_mode": "require_ready_bundle",
            "default_expiry_seconds": 3600,
            "transient_conflict_action": "require_confirmation",
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
        node, customer, plan = await self.ready_bundle()
        topup = await self.post(
            "/v1/admin/payments/topups",
            {"customer_id": customer["id"], "amount_rial": 120000},
        )
        await self.post(
            f"/v1/admin/payments/topups/{topup['id']}/approve",
            {
                "expected_revision": 1,
                "bank_reference": "manualretry_" + self.suffix,
            },
        )
        async with self.app.state.dishka_container() as scope:
            offer = await (await scope.get(ICheckoutOfferQuery)).get(
                customer["id"], plan["id"]
            )
            command = await scope.get(ICheckoutIntentCommand)
            intent = await command.create(
                customer["id"],
                CheckoutCreate(
                    request_key="manualretry_" + self.suffix,
                    plan_id=plan["id"],
                    funding_mode="wallet_only",
                    expected_offer_sha256=offer.offer_sha256,
                    expected_price_rial=offer.price_rial,
                    auto_renew=False,
                    expiry_seconds=3600,
                    changed_offer_action="require_confirmation",
                ),
            )
            intent_id = intent.id
        async with self.connection.uow() as holder:
            async with transaction(holder):
                await holder.execute(
                    text("SELECT id FROM tbl_nodes WHERE id=:id FOR UPDATE"),
                    {"id": node["id"]},
                )
                failure = await asyncio.wait_for(
                    asyncio.create_task(
                        self.recover_native(intent_id), context=Context()
                    ),
                    5,
                )
                self.assertEqual(failure.state, "action_required")
                self.assertEqual(failure.reason_code, "checkout_offer_busy")
        pending = await self.recover_native(intent_id)
        self.assertEqual(pending.state, "action_required")
        self.assertIsNone(pending.subscription_id)
        # Genuine product changes always require confirmation.
        prefs = (await self.get("/v1/admin/settings"))["data"]
        prefs["values"]["purchase_checkout"]["transient_conflict_action"] = (
            "retry_until_expiry"
        )
        saved = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": prefs["revision"],
                "values": prefs["values"],
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        async with self.app.state.dishka_container() as scope:
            command = await scope.get(ICheckoutIntentCommand)
            changed = await command.create(
                customer["id"],
                CheckoutCreate(
                    request_key="truechange_" + self.suffix,
                    plan_id=plan["id"],
                    funding_mode="wallet_only",
                    expected_offer_sha256=offer.offer_sha256,
                    expected_price_rial=offer.price_rial,
                    auto_renew=False,
                    expiry_seconds=3600,
                    changed_offer_action="require_confirmation",
                ),
            )
            changed_id = changed.id
        edited = await self.client.patch(
            f"/v1/admin/plans/{plan['id']}",
            headers=self.headers,
            json={"price_rial": 110000},
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        changed = await self.recover_native(changed_id)
        self.assertEqual(
            (changed.state, changed.reason_code),
            ("action_required", "checkout_offer_changed"),
        )
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        "UPDATE tbl_checkout_intents SET "
                        "expires_at=UTC_TIMESTAMP()-INTERVAL 1 SECOND "
                        "WHERE id=:id"
                    ),
                    {"id": intent_id},
                )
        expired = await self.recover_native(intent_id)
        self.assertEqual(expired.state, "expired")
        self.assertIsNone(expired.subscription_id)
        async with self.connection.uow() as unit:
            result = await unit.execute(
                text(
                    "SELECT balance_rial FROM tbl_wallets WHERE "
                    "customer_id=:id"
                ),
                {"id": customer["id"]},
            )
            self.assertEqual(result.scalar_one(), 120000)
            result = await unit.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_wallet_entries e JOIN "
                    "tbl_wallets w ON w.id=e.wallet_id WHERE "
                    "w.customer_id=:id AND e.reason='purchase'"
                ),
                {"id": customer["id"]},
            )
            self.assertEqual(result.scalar_one(), 0)
            result = await unit.execute(
                text(
                    "SELECT kind,COUNT(*) notice_count FROM "
                    "tbl_notifications WHERE customer_id=:id AND kind "
                    "LIKE 'checkout_%' GROUP BY kind"
                ),
                {"id": customer["id"]},
            )
            self.assertEqual(
                {row.kind: row.notice_count for row in result},
                {"checkout_action_required": 2, "checkout_expired": 1},
            )

    async def test_current_template_disable_after_customer_lock_wait(self):
        from papilio.infra.db.uow import MySQLUnitOfWork

        from src.config.settings import NotificationSettings
        from src.modules.operations.notifications.interfaces import (
            INotificationDeliveryCommand,
        )
        from tests.test_checkout_financial_locks_workflow import (
            wait_native_query,
        )

        await self.enable_manual_checkout()
        prefs = await self.configure_checkout_notices()
        prefs["values"]["notifications"].update(
            channel_mode="both", delivery_enabled=True
        )
        saved = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": prefs["revision"],
                "values": prefs["values"],
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        raw = self.settings.notifications.model_dump()
        raw.update(
            outbound_enabled=True,
            allow_loopback_http=True,
            endpoint="http://127.0.0.1:9/deliver",
            delivery_key="owned-policy-current-fixture-key-32",
        )
        self.settings.notifications = NotificationSettings.model_validate(raw)
        identity, headers, _, intent = await self.pending_intent(
            "policycurrent"
        )
        response = await self.client.post(
            f"/v1/bot/checkouts/{intent['id']}/cancel",
            headers=headers,
            json={
                **identity,
                "request_key": "policycancel_" + self.suffix,
                "expected_revision": intent["revision"],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        async with self.connection.uow() as unit:
            result = await unit.execute(
                text(
                    "SELECT id FROM tbl_notifications "
                    "WHERE kind='checkout_cancelled' AND record_id=:id"
                ),
                {"id": intent["id"]},
            )
            notice_id = result.scalar_one()
        async with self.app.state.dishka_container() as scope:
            delivery = await scope.get(INotificationDeliveryCommand)
            claim = await delivery.claim(notice_id)
            self.assertIsNotNone(claim)
        connected = asyncio.get_running_loop().create_future()

        async def authorize():
            async with self.app.state.dishka_container() as scope:
                unit = await scope.get(MySQLUnitOfWork)
                result = await unit.execute(text("SELECT CONNECTION_ID()"))
                connected.set_result(result.scalar_one())
                delivery = await scope.get(INotificationDeliveryCommand)
                result = await delivery.begin_send(
                    notice_id, claim.claim_token
                )
                return result

        async def disable_policy():
            latest = (await self.get("/v1/admin/settings"))["data"]
            latest["values"]["notifications"]["templates"][
                "checkout_cancelled"
            ]["enabled"] = False
            saved = await self.client.put(
                "/v1/admin/settings",
                headers=self.headers,
                json={
                    "expected_revision": latest["revision"],
                    "values": latest["values"],
                },
            )
            return saved

        async with self.connection.uow() as holder:
            async with transaction(holder):
                await holder.execute(
                    text(
                        "SELECT id FROM tbl_customers WHERE id=:id FOR UPDATE"
                    ),
                    {"id": intent["customer_id"]},
                )
                authorizing = asyncio.create_task(
                    authorize(), context=Context()
                )
                try:
                    connection_id = await asyncio.wait_for(connected, 5)
                    await asyncio.to_thread(
                        wait_native_query,
                        self.raw["db"]["dsn"],
                        connection_id,
                        ("FROM tbl_customers",),
                    )
                    saved = await asyncio.create_task(
                        disable_policy(), context=Context()
                    )
                    self.assertEqual(saved.status_code, 200, saved.text)
                except BaseException:
                    authorizing.cancel()
                    await asyncio.gather(authorizing, return_exceptions=True)
                    raise
        authorized = await asyncio.wait_for(authorizing, 5)
        self.assertIsNone(authorized)
        async with self.connection.uow() as unit:
            result = await unit.execute(
                text(
                    "SELECT outcome FROM tbl_notification_attempts "
                    "WHERE notification_id=:id"
                ),
                {"id": notice_id},
            )
            self.assertEqual(result.scalar_one(), "started")

    async def test_busy_failure_deadline_is_current_after_policy_lock_wait(
        self,
    ):
        from papilio.infra.db.uow import MySQLUnitOfWork

        from tests.checkout_deadline_observation import (
            wait_owned_checkout_expired,
        )
        from tests.test_checkout_financial_locks_workflow import (
            wait_native_query,
        )

        await self.enable_manual_checkout()
        await self.configure_checkout_notices()
        _, _, _, intent = await self.pending_intent("deadlinewait")
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        "UPDATE tbl_checkout_intents "
                        "SET expires_at=UTC_TIMESTAMP()+INTERVAL 4 SECOND "
                        "WHERE id=:id"
                    ),
                    {"id": intent["id"]},
                )
        connected = asyncio.get_running_loop().create_future()

        async def record_failure():
            async with self.app.state.dishka_container() as scope:
                unit = await scope.get(MySQLUnitOfWork)
                result = await unit.execute(text("SELECT CONNECTION_ID()"))
                connected.set_result(result.scalar_one())
                command = await scope.get(ICheckoutIntentCommand)
                result = await command.record_failure(
                    intent["id"], "checkout_offer_busy"
                )
                return result

        async with self.connection.uow() as holder:
            async with transaction(holder):
                await holder.execute(
                    text(
                        "SELECT id FROM tbl_preferences_revisions "
                        "ORDER BY revision DESC LIMIT 1 FOR UPDATE"
                    )
                )
                recording = asyncio.create_task(
                    record_failure(), context=Context()
                )
                try:
                    connection_id = await asyncio.wait_for(connected, 5)
                    await asyncio.to_thread(
                        wait_native_query,
                        self.raw["db"]["dsn"],
                        connection_id,
                        ("FROM tbl_preferences_revisions",),
                    )
                    await asyncio.to_thread(
                        wait_owned_checkout_expired,
                        self.raw["db"]["dsn"],
                        intent["id"],
                    )
                except BaseException:
                    recording.cancel()
                    await asyncio.gather(recording, return_exceptions=True)
                    raise
        expired = await asyncio.wait_for(recording, 5)
        self.assertEqual(expired.state, "expired")
        self.assertEqual(expired.reason_code, "checkout_expired")
        self.assertIsNone(expired.subscription_id)
        async with self.connection.uow() as unit:
            result = await unit.execute(
                text(
                    "SELECT state,reason_code,subscription_id "
                    "FROM tbl_checkout_intents WHERE id=:id"
                ),
                {"id": intent["id"]},
            )
            self.assertEqual(
                tuple(result.one()), ("expired", "checkout_expired", None)
            )
            result = await unit.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_wallet_entries e "
                    "JOIN tbl_wallets w "
                    "ON w.id=e.wallet_id WHERE w.customer_id=:id"
                ),
                {"id": intent["customer_id"]},
            )
            self.assertEqual(result.scalar_one(), 0)

    async def test_funded_attempt_expiry_after_plan_wait_prevents_charge(self):
        from papilio.infra.db.uow import MySQLUnitOfWork

        from tests.checkout_deadline_observation import (
            wait_owned_checkout_expired,
        )
        from tests.test_checkout_financial_locks_workflow import (
            wait_native_query,
        )

        await self.enable_manual_checkout()
        await self.configure_checkout_notices()
        _, _, _, intent = await self.pending_intent("admissiondeadline")
        await self.post(
            f"/v1/admin/payments/topups/{intent['topup_id']}/approve",
            {
                "expected_revision": 1,
                "bank_reference": "admissiondeadline_" + self.suffix,
            },
        )
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        "UPDATE tbl_checkout_intents "
                        "SET expires_at=UTC_TIMESTAMP()+INTERVAL 4 SECOND "
                        "WHERE id=:id"
                    ),
                    {"id": intent["id"]},
                )
        connected = asyncio.get_running_loop().create_future()

        async def attempt():
            async with self.app.state.dishka_container() as scope:
                unit = await scope.get(MySQLUnitOfWork)
                connection_id = await unit.execute(
                    text("SELECT CONNECTION_ID()")
                )
                connected.set_result(connection_id.scalar_one())
                command = await scope.get(ICheckoutIntentCommand)
                result = await command.attempt(intent["id"])
                return result

        async with self.connection.uow() as holder:
            async with transaction(holder):
                await holder.execute(
                    text("SELECT id FROM tbl_plans WHERE id=:id FOR UPDATE"),
                    {"id": intent["plan_id"]},
                )
                purchasing = asyncio.create_task(attempt(), context=Context())
                try:
                    connection_id = await asyncio.wait_for(connected, 5)
                    await asyncio.to_thread(
                        wait_native_query,
                        self.raw["db"]["dsn"],
                        connection_id,
                        ("FROM tbl_plans",),
                    )
                    await asyncio.to_thread(
                        wait_owned_checkout_expired,
                        self.raw["db"]["dsn"],
                        intent["id"],
                    )
                except BaseException:
                    purchasing.cancel()
                    await asyncio.gather(purchasing, return_exceptions=True)
                    raise
        result = await asyncio.wait_for(purchasing, 10)
        async with self.connection.uow() as unit:
            facts = await unit.execute(
                text(
                    "SELECT i.state,i.reason_code,i.subscription_id,"
                    "w.balance_rial,SUM(e.reason='purchase') debits,"
                    "SUM(e.reason='approved_topup') credits "
                    "FROM tbl_checkout_intents i JOIN tbl_wallets w "
                    "ON w.customer_id=i.customer_id "
                    "JOIN tbl_wallet_entries e ON e.wallet_id=w.id "
                    "WHERE i.id=:id GROUP BY i.state,i.reason_code,"
                    "i.subscription_id,w.balance_rial"
                ),
                {"id": intent["id"]},
            )
            persisted = tuple(facts.one())
            expiry_notice = await unit.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_notifications "
                    "WHERE kind='checkout_expired' AND record_id=:id"
                ),
                {"id": intent["id"]},
            )
            notice_count = expiry_notice.scalar_one()
        with self.subTest("immutable purchase admission deadline"):
            self.assertEqual(
                (result.state, result.subscription_id), ("expired", None)
            )
        with self.subTest("committed credit retained without purchase"):
            self.assertEqual(
                persisted, ("expired", "checkout_expired", None, 120000, 0, 1)
            )
        with self.subTest("single expiry notice"):
            self.assertEqual(notice_count, 1)
