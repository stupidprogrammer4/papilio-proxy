"""Native financial and FK lock-order acceptance for durable checkout."""

import asyncio
import time
from contextvars import Context

import pymysql
from papilio.infra.db.transaction import transaction
from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import text
from sqlalchemy.engine import make_url

from src.modules.billing.wallet.domain.dtos import TopupApproval
from src.modules.billing.wallet.interfaces import IWalletCommand
from src.modules.sales.checkout.interfaces import ICheckoutIntentCommand
from tests.test_checkout_workflow import CheckoutWorkflowTest


def wait_native_query(dsn, connection_id, fragments):
    """Observe actual native SQL through a separate read-only sync monitor."""
    url = make_url(dsn)
    monitor = pymysql.connect(
        host=url.host or "127.0.0.1",
        port=url.port or 3306,
        user=url.username,
        password=url.password or "",
        database=url.database,
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=5,
        write_timeout=5,
    )
    previous = None
    try:
        deadline = time.monotonic() + 5
        with monitor.cursor() as cursor:
            while time.monotonic() < deadline:
                cursor.execute("SHOW FULL PROCESSLIST")
                for process in cursor.fetchall():
                    info = process["Info"] or ""
                    if process["Id"] == connection_id and any(
                        fragment in info for fragment in fragments
                    ):
                        if info == previous:
                            return info
                        previous = info
        raise AssertionError("Native SQL lock boundary not observed")
    finally:
        monitor.close()


class CheckoutFinancialLocksWorkflowTest(CheckoutWorkflowTest):
    async def test_payment_notice_approval_and_checkout_native_lock_order(
        self,
    ):
        await self.exercise_financial_lock_order(plan_barrier=False)

    async def test_payment_notice_plan_barrier_native_lock_order(self):
        await self.exercise_financial_lock_order(plan_barrier=True)

    async def exercise_financial_lock_order(self, *, plan_barrier):
        await self.enable_manual_checkout()
        _, _, _, intent = await self.pending_intent(suffix="financiallocks")
        seed = await self.post(
            "/v1/admin/payments/topups",
            {"customer_id": intent["customer_id"], "amount_rial": 30000},
        )
        await self.post(
            f"/v1/admin/payments/topups/{seed['id']}/approve",
            {
                "expected_revision": 1,
                "bank_reference": "lockseed_" + self.suffix,
            },
        )
        prefs = (await self.get("/v1/admin/settings"))["data"]
        policy = prefs["values"]["notifications"]
        policy["enabled"] = True
        policy["channel_mode"] = "inbox"
        policy["delivery_enabled"] = False
        policy["templates"]["payment_approved"]["enabled"] = True
        saved = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": prefs["revision"],
                "values": prefs["values"],
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        async with self.connection.uow() as unit:
            staff_id = (
                await unit.execute(text("SELECT MIN(id) FROM tbl_staff"))
            ).scalar_one()

        connections = {}
        approve_started = asyncio.Event()
        checkout_started = asyncio.Event()

        async def approve():
            async with self.app.state.dishka_container() as scope:
                unit = await scope.get(MySQLUnitOfWork)
                command = await scope.get(IWalletCommand)
                async with transaction(unit):
                    connections["approve"] = (
                        await unit.execute(text("SELECT CONNECTION_ID()"))
                    ).scalar_one()
                    approve_started.set()
                    result = await command.approve(
                        intent["topup_id"],
                        TopupApproval(
                            expected_revision=1,
                            bank_reference="lockapproved_" + self.suffix,
                        ),
                        staff_id,
                    )
                return result

        async def checkout():
            async with self.app.state.dishka_container() as scope:
                unit = await scope.get(MySQLUnitOfWork)
                command = await scope.get(ICheckoutIntentCommand)
                async with transaction(unit):
                    connections["checkout"] = (
                        await unit.execute(text("SELECT CONNECTION_ID()"))
                    ).scalar_one()
                    checkout_started.set()
                    result = await command.attempt(intent["id"])
                return result

        tasks = []
        purchase = None
        try:
            async with self.connection.uow() as holder:
                async with transaction(holder):
                    await holder.execute(
                        text(
                            "SELECT id FROM tbl_plans WHERE id=:id FOR UPDATE"
                            if plan_barrier
                            else "SELECT id FROM tbl_wallets "
                            "WHERE customer_id=:id FOR UPDATE"
                        ),
                        {
                            "id": intent["plan_id"]
                            if plan_barrier
                            else intent["customer_id"]
                        },
                    )
                    if plan_barrier:
                        purchase = asyncio.create_task(
                            checkout(), context=Context()
                        )
                        tasks.append(purchase)
                        await asyncio.wait_for(checkout_started.wait(), 3)
                        await asyncio.to_thread(
                            wait_native_query,
                            self.raw["db"]["dsn"],
                            connections["checkout"],
                            ("tbl_plans",),
                        )
                    approval = asyncio.create_task(
                        approve(), context=Context()
                    )
                    tasks.append(approval)
                    await asyncio.wait_for(approve_started.wait(), 3)
                    await asyncio.to_thread(
                        wait_native_query,
                        self.raw["db"]["dsn"],
                        connections["approve"],
                        ("tbl_wallets", "tbl_customers")
                        if plan_barrier
                        else ("tbl_wallets",),
                    )
                    if not plan_barrier:
                        purchase = asyncio.create_task(
                            checkout(), context=Context()
                        )
                        tasks.append(purchase)
                        await asyncio.wait_for(checkout_started.wait(), 3)
                        await asyncio.to_thread(
                            wait_native_query,
                            self.raw["db"]["dsn"],
                            connections["checkout"],
                            ("tbl_topups", "tbl_customers"),
                        )
                    assert purchase is not None
                    self.assertFalse(approval.done())
                    self.assertFalse(purchase.done())
                # Release only the external row lock. Actual owning commands
                # must now finish without a Customer<->Topup FK deadlock.
            assert purchase is not None
            outcomes = await asyncio.wait_for(
                asyncio.gather(approval, purchase, return_exceptions=True), 10
            )
            for outcome in outcomes:
                self.assertNotIsInstance(outcome, BaseException)
            approved, purchased = outcomes
            assert not isinstance(approved, BaseException)
            assert not isinstance(purchased, BaseException)
            self.assertEqual(approved.status, "approved")
            if plan_barrier and purchased.state == "awaiting_funding":
                from src.modules.sales.checkout.interfaces import (
                    ICheckoutRecoveryRunner,
                )

                async with self.app.state.dishka_container() as scope:
                    runner = await scope.get(ICheckoutRecoveryRunner)
                    purchased = await runner.run(intent["id"])
            self.assertEqual(purchased.state, "purchased")
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        async with self.connection.uow() as unit:
            values = (
                (
                    await unit.execute(
                        text(
                            "SELECT w.balance_rial,"
                            "(SELECT COUNT(*) FROM tbl_wallet_entries e "
                            "WHERE e.wallet_id=w.id "
                            "AND e.reference=:reference) credit_count,"
                            "(SELECT COUNT(*) FROM tbl_wallet_entries e "
                            "WHERE e.wallet_id=w.id AND e.reason='purchase') "
                            "debit_count,"
                            "(SELECT COUNT(*) FROM tbl_notifications n "
                            "WHERE n.event_key=:event) notice_count,"
                            "(SELECT COUNT(*) FROM tbl_subscriptions s "
                            "WHERE s.customer_id=w.customer_id) "
                            "subscription_count "
                            "FROM tbl_wallets w WHERE w.customer_id=:customer"
                        ),
                        {
                            "customer": intent["customer_id"],
                            "reference": f"topup:{intent['topup_id']}",
                            "event": f"payment:{intent['topup_id']}:approved",
                        },
                    )
                )
                .mappings()
                .one()
            )
        self.assertEqual(tuple(values.values()), (50000, 1, 1, 1, 1))
