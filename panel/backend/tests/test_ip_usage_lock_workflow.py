import asyncio
from contextvars import Context

from papilio.infra.db.transaction import transaction
from papilio.security.crypto import hash_sha256
from sqlalchemy import text

from .lock_observation import MySQLLockObservation
from .test_ip_limit_workflow import IpLimitWorkflowFixture


class IpUsageLockWorkflowTest(IpLimitWorkflowFixture):
    async def test_refund_refuses_payer_changed_during_native_customer_wait(
        self,
    ):
        customer, subscription = await self.paid_subscription()
        id = subscription["id"]
        new_payer = await self.post(
            "/v1/admin/customers", {"display_name": "Synthetic changed payer"}
        )
        refund = None
        try:
            async with self.connection.uow() as holder:
                async with transaction(holder):
                    await holder.execute(
                        text(
                            "SELECT id FROM tbl_customers WHERE id=:id FOR"
                            " UPDATE"
                        ),
                        {"id": customer["id"]},
                    )
                    refund = asyncio.create_task(
                        self.client.post(
                            f"/v1/admin/subscriptions/{id}/provision-failed",
                            headers=self.headers,
                            json={"reason": "Synthetic changed payer failure"},
                        ),
                        context=Context(),
                    )
                    self.assertTrue(await self.observe_wait("tbl_customers"))
                    await holder.execute(
                        text(
                            "UPDATE tbl_subscriptions SET payer_customer_i"
                            "d=:payer WHERE id=:id"
                        ),
                        {"id": id, "payer": new_payer["id"]},
                    )
            response = await asyncio.wait_for(refund, 12)
            self.assertEqual(response.status_code, 409)
        finally:
            if refund is not None and not refund.done():
                refund.cancel()
                await asyncio.gather(refund, return_exceptions=True)
        async with self.connection.uow() as fresh:
            state = await fresh.execute(
                text(
                    "SELECT status,payer_customer_id FROM tbl_subscription"
                    "s WHERE id=:id"
                ),
                {"id": id},
            )
            self.assertEqual(
                tuple(state.one()), ("pending_provision", new_payer["id"])
            )
            refunds = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_wallet_entries WHERE referen"
                    "ce=:reference"
                ),
                {"reference": f"provision_refund:{id}:0"},
            )
            self.assertEqual(refunds.scalar_one(), 0)
            balance = await fresh.execute(
                text(
                    "SELECT balance_rial FROM tbl_wallets WHERE customer_i"
                    "d=:id"
                ),
                {"id": customer["id"]},
            )
            self.assertEqual(balance.scalar_one(), 200000)

    async def test_refund_refuses_owner_changed_during_native_customer_wait(
        self,
    ):
        customer, subscription = await self.paid_subscription()
        id = subscription["id"]
        new_owner = await self.post(
            "/v1/admin/customers", {"display_name": "Synthetic changed owner"}
        )
        refund = None
        try:
            async with self.connection.uow() as holder:
                async with transaction(holder):
                    await holder.execute(
                        text(
                            "SELECT id FROM tbl_customers WHERE id=:id FOR"
                            " UPDATE"
                        ),
                        {"id": customer["id"]},
                    )
                    refund = asyncio.create_task(
                        self.client.post(
                            f"/v1/admin/subscriptions/{id}/provision-failed",
                            headers=self.headers,
                            json={"reason": "Synthetic changed owner failure"},
                        ),
                        context=Context(),
                    )
                    self.assertTrue(await self.observe_wait("tbl_customers"))
                    await holder.execute(
                        text(
                            "UPDATE tbl_subscriptions SET customer_id=:own"
                            "er WHERE id=:id"
                        ),
                        {"id": id, "owner": new_owner["id"]},
                    )
            response = await asyncio.wait_for(refund, 12)
            self.assertEqual(response.status_code, 409)
        finally:
            if refund is not None and not refund.done():
                refund.cancel()
                await asyncio.gather(refund, return_exceptions=True)
        async with self.connection.uow() as fresh:
            state = await fresh.execute(
                text(
                    "SELECT status,customer_id FROM tbl_subscriptions WHER"
                    "E id=:id"
                ),
                {"id": id},
            )
            self.assertEqual(
                tuple(state.one()), ("pending_provision", new_owner["id"])
            )
            refunds = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_wallet_entries WHERE referen"
                    "ce=:reference"
                ),
                {"reference": f"provision_refund:{id}:0"},
            )
            self.assertEqual(refunds.scalar_one(), 0)
            balance = await fresh.execute(
                text(
                    "SELECT balance_rial FROM tbl_wallets WHERE customer_i"
                    "d=:id"
                ),
                {"id": customer["id"]},
            )
            self.assertEqual(balance.scalar_one(), 200000)

    async def test_allocation_rechecks_rotated_key_after_native_node_wait(
        self,
    ):
        _, subscription, nodes = await self.seed_assigned_subscription()
        id = subscription["id"]
        node = nodes[0]
        async with self.connection.uow() as unit:
            profile = await unit.execute(
                text(
                    "SELECT id FROM tbl_profiles WHERE subscription_id=:id "
                    "AND configuration_id=:configuration"
                ),
                {"id": id, "configuration": node["configuration_id"]},
            )
            profile_id = profile.scalar_one()
        new_digest = await asyncio.to_thread(
            hash_sha256, "synthetic-replacement-key"
        )
        allocation = None
        try:
            async with self.connection.uow() as holder:
                async with transaction(holder):
                    await holder.execute(
                        text(
                            "SELECT id FROM tbl_nodes WHERE id=:id FOR UPDATE"
                        ),
                        {"id": node["node"]["id"]},
                    )
                    allocation = asyncio.create_task(
                        self.client.post(
                            f"/v1/nodes/{node['node']['code']}/usage/grants",
                            headers={"X-Papilio-Node-Key": node["agent_key"]},
                            json={
                                "profile_id": profile_id,
                                "generation": 0,
                                "request_key": "rotated_" + self.suffix,
                                "requested_bytes": 1024,
                            },
                        ),
                        context=Context(),
                    )
                    self.assertTrue(await self.observe_wait("tbl_nodes"))
                    await holder.execute(
                        text(
                            "UPDATE tbl_nodes SET agent_key_hash=:digest W"
                            "HERE id=:id"
                        ),
                        {"id": node["node"]["id"], "digest": new_digest},
                    )
            response = await asyncio.wait_for(allocation, 12)
            self.assertEqual(response.status_code, 401)
        finally:
            if allocation is not None and not allocation.done():
                allocation.cancel()
                await asyncio.gather(allocation, return_exceptions=True)
        async with self.connection.uow() as fresh:
            grants = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_usage_grants WHERE subscript"
                    "ion_id=:id"
                ),
                {"id": id},
            )
            self.assertEqual(grants.scalar_one(), 0)

    async def test_native_allocation_and_ip_admission_have_no_lock_cycle(self):
        customer, subscription, nodes = await self.seed_assigned_subscription()
        id = subscription["id"]
        node = nodes[0]
        await self.configure(id)
        async with self.connection.uow() as unit:
            profile = await unit.execute(
                text(
                    "SELECT id FROM tbl_profiles WHERE subscription_id=:id "
                    "AND configuration_id=:configuration"
                ),
                {"id": id, "configuration": node["configuration_id"]},
            )
            profile_id = profile.scalar_one()
        tasks = []
        try:
            async with self.connection.uow() as holder:
                async with transaction(holder):
                    await holder.execute(
                        text(
                            "SELECT id FROM tbl_subscriptions WHERE id=:id"
                            " FOR UPDATE"
                        ),
                        {"id": id},
                    )
                    allocation = asyncio.create_task(
                        self.client.post(
                            f"/v1/nodes/{node['node']['code']}/usage/grants",
                            headers={"X-Papilio-Node-Key": node["agent_key"]},
                            json={
                                "profile_id": profile_id,
                                "generation": 0,
                                "request_key": "lock_" + self.suffix,
                                "requested_bytes": 1024,
                            },
                        ),
                        context=Context(),
                    )
                    tasks.append(allocation)
                    subscription_wait = await self.observe_wait(
                        "tbl_subscriptions"
                    )
                    self.assertTrue(
                        subscription_wait,
                        "Native allocation Subscription wait missing",
                    )
                    admission = asyncio.create_task(
                        self.admission(node, id, "192.0.2.180"),
                        context=Context(),
                    )
                    tasks.append(admission)
                    node_wait, customer_wait = await asyncio.gather(
                        self.observe_wait("tbl_nodes"),
                        self.observe_wait("tbl_customers"),
                    )
                    # Both are legitimate production waits; success of both
                    # operations is the invariant, independent of lock order.
                    self.assertTrue(
                        node_wait or customer_wait,
                        "Native admission wait missing",
                    )
            outcomes = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), 12
            )
            self.assertFalse(
                [item for item in outcomes if isinstance(item, BaseException)],
                "Valid native operations must not deadlock",
            )
            allocation_result, admission_result = outcomes
            assert not isinstance(allocation_result, BaseException)
            assert not isinstance(admission_result, BaseException)
            self.assertEqual(allocation_result.status_code, 200)
            self.assertTrue(admission_result["allowed"])
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        async with self.connection.uow() as fresh:
            grants = await fresh.execute(
                text(
                    "SELECT COUNT(*),SUM(allocated_bytes) FROM tbl_usage_g"
                    "rants "
                    "WHERE subscription_id=:id"
                ),
                {"id": id},
            )
            self.assertEqual(tuple(grants.one()), (1, 1024))
            sessions = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_ip_sessions WHERE subscripti"
                    "on_id=:id"
                ),
                {"id": id},
            )
            self.assertEqual(sessions.scalar_one(), 1)
            balance = await fresh.execute(
                text(
                    "SELECT balance_rial FROM tbl_wallets WHERE customer_i"
                    "d=:id"
                ),
                {"id": customer["id"]},
            )
            self.assertEqual(balance.scalar_one(), 200000)
        current = (await self.get(f"/v1/admin/subscriptions/{id}"))["data"]
        self.assertEqual(current["used_bytes"], 0)
        self.assertEqual(
            current["purchased_ip_policy"], subscription["purchased_ip_policy"]
        )

    async def test_native_refund_and_ip_admission_have_no_lock_cycle(self):
        customer, subscription = await self.paid_subscription()
        id = subscription["id"]
        node = await self.register_assignment(id, "refund")
        await self.configure(id)
        tasks = []
        try:
            async with self.connection.uow() as holder:
                async with transaction(holder):
                    await holder.execute(
                        text(
                            "SELECT id FROM tbl_nodes WHERE id=:id FOR UPDATE"
                        ),
                        {"id": node["node"]["id"]},
                    )
                    admission = asyncio.create_task(
                        self.admission(node, id, "192.0.2.181"),
                        context=Context(),
                    )
                    tasks.append(admission)
                    self.assertTrue(await self.observe_wait("tbl_nodes"))
                    refund = asyncio.create_task(
                        self.client.post(
                            f"/v1/admin/subscriptions/{id}/provision-failed",
                            headers=self.headers,
                            json={
                                "reason": (
                                    "Synthetic native provisioning failure"
                                )
                            },
                        ),
                        context=Context(),
                    )
                    tasks.append(refund)
                    self.assertTrue(await self.observe_wait("tbl_customers"))
            outcomes = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), 12
            )
            self.assertFalse(
                [item for item in outcomes if isinstance(item, BaseException)],
                "Valid native operations must not deadlock",
            )
            admission_result, refund_result = outcomes
            assert not isinstance(admission_result, BaseException)
            assert not isinstance(refund_result, BaseException)
            self.assertFalse(admission_result["allowed"])
            self.assertEqual(
                admission_result["reason"], "entitlement_inactive"
            )
            self.assertEqual(refund_result.status_code, 200)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        replay = await self.client.post(
            f"/v1/admin/subscriptions/{id}/provision-failed",
            headers=self.headers,
            json={"reason": "Synthetic native provisioning failure"},
        )
        self.assertEqual(replay.status_code, 200)
        async with self.connection.uow() as fresh:
            ledger = await fresh.execute(
                text(
                    "SELECT SUM(e.amount_rial),SUM(e.reason='provision_ref"
                    "und'),"
                    "SUM(e.reason='purchase') FROM tbl_wallet_entries e "
                    "JOIN tbl_wallets w ON w.id=e.wallet_id WHERE w.custom"
                    "er_id=:id"
                ),
                {"id": customer["id"]},
            )
            self.assertEqual(tuple(ledger.one()), (300000, 1, 1))
            balance = await fresh.execute(
                text(
                    "SELECT balance_rial FROM tbl_wallets WHERE customer_i"
                    "d=:id"
                ),
                {"id": customer["id"]},
            )
            self.assertEqual(balance.scalar_one(), 300000)
        current = (await self.get(f"/v1/admin/subscriptions/{id}"))["data"]
        self.assertEqual(current["status"], "failed")
        self.assertEqual(
            current["purchased_ip_policy"], subscription["purchased_ip_policy"]
        )

    async def observe_wait(self, table: str) -> bool:
        observed = await asyncio.to_thread(
            MySQLLockObservation().wait_for_queries,
            self.raw["db"]["dsn"],
            table,
            ("SELECT",),
            1,
            5,
            0.02,
            True,
        )
        return observed
