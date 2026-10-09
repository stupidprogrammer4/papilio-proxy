"""Current node permission after a real customer-lock wait."""

import asyncio
from contextvars import Context

from papilio.infra.db.transaction import transaction
from sqlalchemy import text

from tests.lock_observation import MySQLLockObservation
from tests.test_ip_limit_workflow import IpLimitWorkflowFixture


class IpPolicyCurrentWorkflowTest(IpLimitWorkflowFixture):
    async def test_removed_assignment_after_customer_wait_cannot_admit(self):
        customer, subscription, nodes = await self.seed_assigned_subscription()
        node = nodes[0]
        await self.configure(subscription["id"])
        admission = None
        try:
            async with self.connection.uow() as holder:
                async with transaction(holder):
                    await holder.execute(
                        text(
                            "SELECT id FROM tbl_customers WHERE id=:id "
                            "FOR UPDATE"
                        ),
                        {"id": customer["id"]},
                    )
                    admission = asyncio.create_task(
                        self.client.post(
                            f"/v1/nodes/{node['node']['code']}/ip-admission",
                            headers={"X-Papilio-Node-Key": node["agent_key"]},
                            json={
                                "subscription_id": subscription["id"],
                                "source_ip": "192.0.2.29",
                            },
                        ),
                        context=Context(),
                    )
                    observed = await asyncio.to_thread(
                        MySQLLockObservation().wait_for_queries,
                        self.raw["db"]["dsn"],
                        "tbl_customers",
                        ("SELECT",),
                        1,
                        5,
                        0.02,
                        True,
                    )
                    self.assertTrue(observed, "Native Customer wait missing")
                    self.assertFalse(admission.done())

                    async def remove_assignment():
                        # Isolated stored-assignment removal. No production
                        # remove-profile endpoint or physical core proof is
                        # implied by this native database fault boundary.
                        async with self.connection.uow() as independent:
                            async with transaction(independent):
                                await independent.execute(
                                    text(
                                        "DELETE FROM tbl_profiles WHERE "
                                        "subscription_id=:subscription AND "
                                        "configuration_id=:configuration"
                                    ),
                                    {
                                        "subscription": subscription["id"],
                                        "configuration": node[
                                            "configuration_id"
                                        ],
                                    },
                                )

                    await asyncio.create_task(
                        remove_assignment(), context=Context()
                    )
            response = await asyncio.wait_for(admission, 8)
        finally:
            if admission is not None:
                if not admission.done():
                    admission.cancel()
                await asyncio.gather(admission, return_exceptions=True)
        async with self.connection.uow() as fresh:
            facts = (
                (
                    await fresh.execute(
                        text(
                            "SELECT (SELECT COUNT(*) FROM tbl_profiles WHERE "
                            "subscription_id=:subscription AND configur"
                            "ation_id="
                            ":configuration) profiles, (SELECT COUNT(*) FROM "
                            "tbl_ip_sessions WHERE subscription_id=:sub"
                            "scription "
                            "AND expires_at>UTC_TIMESTAMP(6)) active"
                        ),
                        {
                            "subscription": subscription["id"],
                            "configuration": node["configuration_id"],
                        },
                    )
                )
                .mappings()
                .one()
            )
        self.assertEqual(facts["profiles"], 0)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(facts["active"], 0)

    async def test_node_disabled_during_customer_wait_cannot_admit(self):
        customer, subscription, nodes = await self.seed_assigned_subscription()
        node = nodes[0]
        await self.configure(subscription["id"])
        admission = None
        try:
            async with self.connection.uow() as holder:
                async with transaction(holder):
                    await holder.execute(
                        text(
                            "SELECT id FROM tbl_customers WHERE id=:id "
                            "FOR UPDATE"
                        ),
                        {"id": customer["id"]},
                    )
                    admission = asyncio.create_task(
                        self.admission(node, subscription["id"], "192.0.2.19"),
                        context=Context(),
                    )
                    observed = await asyncio.to_thread(
                        MySQLLockObservation().wait_for_queries,
                        self.raw["db"]["dsn"],
                        "tbl_customers",
                        ("SELECT",),
                        1,
                        5,
                        0.02,
                        True,
                    )
                    self.assertTrue(observed, "Native Customer wait missing")
                    self.assertFalse(admission.done())
                    disabled = await asyncio.create_task(
                        self.client.patch(
                            f"/v1/admin/network/nodes/{node['node']['id']}/enabled",
                            headers=self.headers,
                            json={"enabled": False},
                        ),
                        context=Context(),
                    )
                    self.assertEqual(disabled.status_code, 200, disabled.text)
            result = await asyncio.wait_for(admission, 8)
        finally:
            if admission is not None:
                if not admission.done():
                    admission.cancel()
                await asyncio.gather(admission, return_exceptions=True)
        async with self.connection.uow() as fresh:
            facts = await fresh.execute(
                text(
                    "SELECT n.is_enabled,(SELECT COUNT(*) FROM "
                    "tbl_ip_sessions s WHERE s.subscription_id=:subscription "
                    "AND s.expires_at>UTC_TIMESTAMP(6)) active FROM "
                    "tbl_nodes n WHERE n.id=:node"
                ),
                {
                    "subscription": subscription["id"],
                    "node": node["node"]["id"],
                },
            )
            current = facts.mappings().one()
        self.assertFalse(current["is_enabled"])
        self.assertFalse(
            result["allowed"], "Disabled node admitted new source IP"
        )
        self.assertEqual(current["active"], 0)
