"""Exact native gates for explicit owned checkout-operation retirement."""

from tests.test_checkout_workflow import CheckoutWorkflowTest


class CheckoutRetirementWorkflowTest(CheckoutWorkflowTest):
    async def test_retired_missing_attempt_fences_delayed_create(self):
        await self.enable_manual_checkout()
        identity, headers, body, existing = await self.pending_intent(
            suffix="retirement"
        )
        delayed_body = {**body, "request_key": "delayed_" + self.suffix}
        lookup = await self.client.post(
            "/v1/bot/checkouts/lookup",
            headers=headers,
            json={**identity, "request_key": delayed_body["request_key"]},
        )
        self.assertEqual(lookup.status_code, 404, lookup.text)
        retirement = await self.client.post(
            "/v1/bot/checkouts/retire",
            headers=headers,
            json={**identity, "request_key": delayed_body["request_key"]},
        )
        self.assertEqual(retirement.status_code, 200, retirement.text)
        self.assertEqual(
            retirement.json()["data"],
            {
                "request_key": delayed_body["request_key"],
                "status": "retired",
                "intent": None,
            },
        )
        # This original handler arrives only after durable retirement commits.
        delayed = await self.client.post(
            "/v1/bot/checkouts", headers=headers, json=delayed_body
        )
        self.assertEqual(delayed.status_code, 409, delayed.text)
        self.assertIn("checkout_attempt_retired", delayed.text)
        replay = await self.client.post(
            "/v1/bot/checkouts/retire",
            headers=headers,
            json={**identity, "request_key": delayed_body["request_key"]},
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["data"], retirement.json()["data"])
        history = await self.client.post(
            "/v1/bot/checkouts/history", headers=headers, json=identity
        )
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual(
            [row["id"] for row in history.json()["data"]], [existing["id"]]
        )
        replacement = await self.client.post(
            "/v1/bot/checkouts",
            headers=headers,
            json={**body, "request_key": "replacement_" + self.suffix},
        )
        self.assertEqual(replacement.status_code, 200, replacement.text)
        self.assertNotEqual(replacement.json()["data"]["id"], existing["id"])

    async def test_retirement_owned_replay_late_funding_keeps_wallet(self):
        await self.enable_manual_checkout()
        identity, headers, body, intent = await self.pending_intent(
            suffix="retirementfunding"
        )
        retired = await self.client.post(
            "/v1/bot/checkouts/retire",
            headers=headers,
            json={**identity, "request_key": body["request_key"]},
        )
        self.assertEqual(retired.status_code, 200, retired.text)
        result = retired.json()["data"]
        self.assertEqual(result["status"], "retired")
        self.assertEqual(result["intent"]["state"], "cancelled")
        self.assertEqual(
            result["intent"]["reason_code"], "checkout_attempt_retired"
        )
        replay = await self.client.post(
            "/v1/bot/checkouts", headers=headers, json=body
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["data"], result["intent"])
        foreign = await self.client.post(
            "/v1/bot/checkouts/retire",
            headers=headers,
            json={
                **identity,
                "telegram_id": identity["telegram_id"] + 1,
                "request_key": body["request_key"],
            },
        )
        self.assertEqual(foreign.status_code, 200, foreign.text)
        self.assertIsNone(foreign.json()["data"]["intent"])
        await self.post(
            f"/v1/admin/payments/topups/{intent['topup_id']}/approve",
            {
                "expected_revision": 1,
                "bank_reference": "retirement_" + self.suffix,
            },
        )
        from src.modules.sales.checkout.interfaces import (
            ICheckoutRecoveryRunner,
        )

        async with self.app.state.dishka_container() as scope:
            runner = await scope.get(ICheckoutRecoveryRunner)
            recovered = await runner.run(intent["id"])
            self.assertEqual(recovered.state, "cancelled")
            self.assertIsNone(recovered.subscription_id)
        wallet = (
            await self.get(
                f"/v1/admin/payments/wallets/{intent['customer_id']}"
            )
        )["data"]
        self.assertEqual(wallet["balance_rial"], 120000)

    async def test_populated_0049_backfill_and_guarded_downgrade(self):
        import asyncio
        import hashlib
        import json

        from alembic import command
        from alembic.config import Config
        from papilio.infra.db.transaction import transaction
        from sqlalchemy import text

        await self.enable_manual_checkout()
        _, _, body, intent = await self.pending_intent(suffix="fencemigration")
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", self.raw["db"]["dsn"])
        # Isolated schema only: remove the new fence to reconstruct a real
        # populated previous-version database, preserving all financial rows.
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(text("DELETE FROM tbl_checkout_attempts"))
        await asyncio.to_thread(
            command.downgrade, cfg, "0049_durable_checkout"
        )
        tables = (
            "tbl_staff",
            "tbl_customers",
            "tbl_wallets",
            "tbl_wallet_entries",
            "tbl_topups",
            "tbl_checkout_intents",
            "tbl_checkout_action_receipts",
            "tbl_preferences_revisions",
        )

        async def snapshot(table):
            async with self.connection.uow() as unit:
                rows = await unit.execute(
                    text(f"SELECT * FROM {table} ORDER BY id")
                )
                data = [tuple(row) for row in rows.all()]
            digest = await asyncio.to_thread(
                lambda: hashlib.sha256(
                    json.dumps(data, default=str).encode()
                ).hexdigest()
            )
            return len(data), digest

        before = await asyncio.gather(*(snapshot(table) for table in tables))
        await asyncio.to_thread(
            command.upgrade, cfg, "0050_checkout_attempt_fences"
        )
        after = await asyncio.gather(*(snapshot(table) for table in tables))
        self.assertEqual(before, after)
        async with self.connection.uow() as unit:
            row = (
                (
                    await unit.execute(
                        text(
                            "SELECT a.customer_id,a.request_key,a.body_sha256,"
                            "a.intent_id,a.retired,i.body_sha256 original_sha "
                            "FROM tbl_checkout_attempts a "
                            "JOIN tbl_checkout_intents i ON i.id=a.intent_id "
                            "WHERE i.id=:id"
                        ),
                        {"id": intent["id"]},
                    )
                )
                .mappings()
                .one()
            )
            self.assertEqual(row["customer_id"], intent["customer_id"])
            self.assertEqual(
                row["request_key"],
                f"checkout:{intent['customer_id']}:{body['request_key']}",
            )
            self.assertEqual(row["body_sha256"], row["original_sha"])
            self.assertEqual(row["intent_id"], intent["id"])
            self.assertFalse(row["retired"])
        fence_before = await snapshot("tbl_checkout_attempts")
        with self.assertRaisesRegex(RuntimeError, "attempt fences"):
            await asyncio.to_thread(
                command.downgrade, cfg, "0049_durable_checkout"
            )
        self.assertEqual(fence_before, await snapshot("tbl_checkout_attempts"))
        self.assertEqual(
            before,
            await asyncio.gather(*(snapshot(table) for table in tables)),
        )

    async def test_create_first_retirement_waits_for_native_commit(self):
        import asyncio
        from contextvars import Context

        from papilio.infra.db.transaction import transaction
        from papilio.infra.db.uow import MySQLUnitOfWork

        from src.modules.sales.checkout.domain.attempts import CheckoutRetire
        from src.modules.sales.checkout.domain.contracts import CheckoutCreate
        from src.modules.sales.checkout.interfaces import (
            ICheckoutIntentCommand,
            ICheckoutRetirementCommand,
        )

        await self.enable_manual_checkout()
        _, _, body, previous = await self.pending_intent(suffix="createfirst")
        body = {**body, "request_key": "inflight_" + self.suffix}
        entered = asyncio.Event()

        async def retire():
            async with self.app.state.dishka_container() as scope:
                command = await scope.get(ICheckoutRetirementCommand)
                entered.set()
                result = await command.retire(
                    previous["customer_id"],
                    CheckoutRetire(request_key=body["request_key"]),
                )
                return result

        task = None
        try:
            async with self.app.state.dishka_container() as scope:
                unit = await scope.get(MySQLUnitOfWork)
                command = await scope.get(ICheckoutIntentCommand)
                async with transaction(unit):
                    created = await command.create(
                        previous["customer_id"],
                        CheckoutCreate.model_validate(body),
                    )
                    task = asyncio.create_task(retire(), context=Context())
                    await asyncio.wait_for(entered.wait(), timeout=3)
                    # The competing native command cannot pass the durable
                    # reservation before the real outer create commits.
                    with self.assertRaises(TimeoutError):
                        await asyncio.wait_for(asyncio.shield(task), 0.2)
            retired = await asyncio.wait_for(task, timeout=5)
            self.assertEqual(retired.status, "retired")
            self.assertIsNotNone(retired.intent)
            assert retired.intent is not None
            self.assertEqual(retired.intent.id, created.id)
            self.assertEqual(retired.intent.state, "cancelled")
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_purchase_first_retirement_retains_one_financial_result(
        self,
    ):
        import asyncio
        from contextvars import Context

        from papilio.infra.db.transaction import transaction
        from papilio.infra.db.uow import MySQLUnitOfWork

        from src.modules.sales.checkout.domain.attempts import CheckoutRetire
        from src.modules.sales.checkout.interfaces import (
            ICheckoutIntentCommand,
            ICheckoutRetirementCommand,
        )

        await self.enable_manual_checkout()
        _, _, body, intent = await self.pending_intent(suffix="purchasefirst")
        await self.post(
            f"/v1/admin/payments/topups/{intent['topup_id']}/approve",
            {
                "expected_revision": 1,
                "bank_reference": "purchasefirst_" + self.suffix,
            },
        )
        entered = asyncio.Event()

        async def retire():
            async with self.app.state.dishka_container() as scope:
                command = await scope.get(ICheckoutRetirementCommand)
                entered.set()
                result = await command.retire(
                    intent["customer_id"],
                    CheckoutRetire(request_key=body["request_key"]),
                )
                return result

        task = None
        try:
            async with self.app.state.dishka_container() as scope:
                unit = await scope.get(MySQLUnitOfWork)
                command = await scope.get(ICheckoutIntentCommand)
                async with transaction(unit):
                    purchased = await command.attempt(intent["id"])
                    self.assertEqual(purchased.state, "purchased")
                    task = asyncio.create_task(retire(), context=Context())
                    await asyncio.wait_for(entered.wait(), timeout=3)
                    with self.assertRaises(TimeoutError):
                        await asyncio.wait_for(asyncio.shield(task), 0.2)
            retired = await asyncio.wait_for(task, timeout=5)
            self.assertEqual(retired.status, "purchased")
            assert retired.intent is not None
            self.assertEqual(
                retired.intent.subscription_id, purchased.subscription_id
            )
            self.assertEqual(retired.intent.state, "purchased")
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        wallet = (
            await self.get(
                f"/v1/admin/payments/wallets/{intent['customer_id']}"
            )
        )["data"]
        self.assertEqual(wallet["balance_rial"], 20000)

    async def test_different_keys_same_customer_create_without_deadlock(self):
        import asyncio
        from contextvars import Context

        await self.enable_manual_checkout()
        _, headers, body, original = await self.pending_intent(
            suffix="parallelkeys"
        )
        first = {**body, "request_key": "parallel_a_" + self.suffix}
        second = {**body, "request_key": "parallel_b_" + self.suffix}
        responses = await asyncio.wait_for(
            asyncio.gather(
                asyncio.create_task(
                    self.client.post(
                        "/v1/bot/checkouts", headers=headers, json=first
                    ),
                    context=Context(),
                ),
                asyncio.create_task(
                    self.client.post(
                        "/v1/bot/checkouts", headers=headers, json=second
                    ),
                    context=Context(),
                ),
            ),
            timeout=10,
        )
        for response in responses:
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(
                response.json()["data"]["customer_id"],
                original["customer_id"],
            )
        self.assertNotEqual(
            responses[0].json()["data"]["id"],
            responses[1].json()["data"]["id"],
        )
        self.assertNotEqual(
            responses[0].json()["data"]["topup_id"],
            responses[1].json()["data"]["topup_id"],
        )
