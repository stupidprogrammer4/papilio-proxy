"""Real admission/renewal lock intersection; fixture profiles are API-only."""

import asyncio
from contextvars import Context
from datetime import UTC, datetime, timedelta

from papilio.infra.db.transaction import transaction
from sqlalchemy import select, text
from sqlmodel import col

from src.modules.billing.wallet.infra.tables import (
    WalletEntryTable,
    WalletTable,
)
from src.modules.sales.subscriptions.interfaces import ISubscriptionCommand
from tests.lock_observation import MySQLLockObservation
from tests.test_ip_limit_workflow import IpLimitWorkflowFixture


class IpRenewalLockWorkflowTest(IpLimitWorkflowFixture):
    async def test_admission_and_due_renewal_complete_without_deadlock(self):
        customer, subscription = await self.paid_subscription(auto_renew=True)
        nodes = await asyncio.gather(
            self.register_assignment(subscription["id"], "lock_a"),
            self.register_assignment(subscription["id"], "lock_b"),
        )
        node = nodes[0]
        await self.configure(subscription["id"])
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        "UPDATE tbl_subscriptions SET status='active',"
                        "provisioning_managed=0,expires_at=:due WHERE id=:id"
                    ),
                    {
                        "id": subscription["id"],
                        "due": datetime.now(UTC).replace(tzinfo=None)
                        - timedelta(seconds=1),
                    },
                )

        async def renew():
            async with self.app.state.dishka_container() as scope:
                command = await scope.get(ISubscriptionCommand)
                result = await command.renew_due(subscription["id"])
                return result.renewal_count

        tasks = []
        try:
            # The external holder only delays the real node lock. Admission
            # owns its production Customer lock; renewal owns its production
            # Subscription lock. No business service or reader is replaced.
            async with self.connection.uow() as holder:
                async with transaction(holder):
                    await holder.execute(
                        text(
                            "SELECT id FROM tbl_nodes WHERE id=:id FOR UPDATE"
                        ),
                        {"id": node["node"]["id"]},
                    )
                    admission = asyncio.create_task(
                        self.admission(node, subscription["id"], "192.0.2.71"),
                        context=Context(),
                    )
                    tasks.append(admission)
                    node_wait = await asyncio.to_thread(
                        MySQLLockObservation().wait_for_queries,
                        self.raw["db"]["dsn"],
                        "tbl_nodes",
                        ("SELECT",),
                        1,
                        5,
                        0.02,
                        True,
                    )
                    self.assertTrue(
                        node_wait, "Native admission Node wait missing"
                    )
                    renewal = asyncio.create_task(renew(), context=Context())
                    tasks.append(renewal)
                    customer_wait = await asyncio.to_thread(
                        MySQLLockObservation().wait_for_queries,
                        self.raw["db"]["dsn"],
                        "tbl_customers",
                        ("SELECT",),
                        1,
                        5,
                        0.02,
                        True,
                    )
                    self.assertTrue(
                        customer_wait, "Native renewal Customer wait missing"
                    )
            outcomes = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), 12
            )
            failures = [
                item for item in outcomes if isinstance(item, BaseException)
            ]
            self.assertFalse(
                failures, "Valid native operations must not deadlock"
            )
            self.assertEqual(outcomes[1], 1)
        finally:
            for pending in tasks:
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        current = (
            await self.get(f"/v1/admin/subscriptions/{subscription['id']}")
        )["data"]
        self.assertEqual(current["renewal_count"], 1)
        self.assertEqual(current["status"], "pending_provision")
        self.assertEqual(
            current["purchased_ip_policy"], subscription["purchased_ip_policy"]
        )
        async with self.connection.uow() as fresh:
            result = await fresh.execute(
                select(WalletEntryTable)
                .join(
                    WalletTable,
                    col(WalletTable.id) == col(WalletEntryTable.wallet_id),
                )
                .where(col(WalletTable.customer_id) == customer["id"])
            )
            ledger = result.scalars().all()
            profiles = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_profiles "
                    "WHERE subscription_id=:id"
                ),
                {"id": subscription["id"]},
            )
            self.assertEqual(profiles.scalar_one(), 2)
        self.assertEqual(sum(item.amount_rial for item in ledger), 100000)
        self.assertEqual(
            sum(item.reason == "auto_renewal" for item in ledger), 1
        )
        self.assertEqual(sum(item.amount_rial > 0 for item in ledger), 1)
