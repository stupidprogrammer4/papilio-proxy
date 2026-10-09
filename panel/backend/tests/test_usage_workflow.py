import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlmodel import col

from src.modules.network.usage.infra.tables import UsageGrantTable
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable
from tests.test_fulfillment_workflow import FulfillmentWorkflowFixture


class UsageWorkflowTest(FulfillmentWorkflowFixture):
    async def renew(self, id):
        from src.modules.sales.subscriptions.interfaces import (
            ISubscriptionCommand,
        )

        async with self.app.state.dishka_container() as scope:
            command = await scope.get(ISubscriptionCommand)
            result = await command.renew_due(id)
            return result.renewal_count

    async def test_expiry_final_usage_revocation_then_one_renewal(self):
        subscription, tasks, nodes, _ = await self.active_sale("reported")
        sid = subscription["id"]
        original_url = (
            await self.post(
                f"/v1/admin/network/configurations/subscriptions/{sid}/link"
            )
        )["url"]
        grant = (await self.allocate(tasks[0], nodes, 100000000)).json()[
            "data"
        ]
        at = datetime.now(UTC).replace(microsecond=0)
        report_body = {
            "upload": 15,
            "download": 25,
            "sampled_at": at,
            "event_id": "final_" + self.suffix,
            "final": True,
        }
        async with self.connection.uow() as independent:
            await independent.execute(
                update(SubscriptionTable)
                .where(col(SubscriptionTable.id) == sid)
                .values(
                    expires_at=datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(seconds=1)
                )
            )
            await independent.commit()
        checked = await self.post(
            f"/v1/admin/subscriptions/{sid}/check-lifecycle"
        )
        self.assertEqual(checked["status"], "revoking")
        self.assertEqual(await self.renew(sid), 0)
        revokes = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        blocked = await self.client.post(
            f"/v1/nodes/{revokes[0][0]['node']['code']}/provisioning/{tasks[0]['id']}/acknowledge",
            headers={"X-Papilio-Node-Key": revokes[0][0]["agent_key"]},
            json={
                "claim_token": revokes[0][1]["claim_token"],
                "outcome": "revoked",
            },
        )
        self.assertEqual(blocked.status_code, 409)
        final = await self.usage(grant, tasks[0], nodes, **report_body)
        self.assertEqual(final.status_code, 200)
        await asyncio.gather(
            *(
                self.ack(task, *claim, outcome="revoked")
                for task, claim in zip(tasks, revokes, strict=True)
            )
        )
        expired = (await self.get(f"/v1/admin/subscriptions/{sid}"))["data"]
        self.assertEqual(expired["status"], "expired")
        wallet_path = (
            f"/v1/admin/payments/wallets/{subscription['customer_id']}"
        )
        self.assertEqual(
            (await self.get(wallet_path))["data"]["balance_rial"], 200000
        )
        self.assertEqual(
            (await self.get(wallet_path + "/entries?reason=provision_refund"))[
                "meta"
            ]["pager"]["total_items"],
            0,
        )
        outcomes = await asyncio.gather(self.renew(sid), self.renew(sid))
        self.assertEqual(outcomes, [1, 1])
        self.assertEqual(
            (await self.get(wallet_path))["data"]["balance_rial"], 100000
        )
        again = await self.usage(grant, tasks[0], nodes, **report_body)
        self.assertEqual(again.status_code, 200)
        current = (await self.get(f"/v1/admin/subscriptions/{sid}"))["data"]
        self.assertEqual(current["used_bytes"], 0)
        request = (
            await self.get(f"/v1/admin/provisioning?subscription_id={sid}")
        )["data"][0]
        self.assertEqual(request["generation"], 1)
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        new_tasks = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"]
        claims = await asyncio.gather(
            *(self.claim(task, nodes) for task in new_tasks)
        )
        await asyncio.gather(
            *(
                self.ack(task, *claim)
                for task, claim in zip(new_tasks, claims, strict=True)
            )
        )
        # A replayed old revoke acknowledgement cannot clear new entitlements.
        await self.ack(tasks[0], *revokes[0], outcome="revoked")
        after_url = (
            await self.post(
                f"/v1/admin/network/configurations/subscriptions/{sid}/link"
            )
        )["url"]
        self.assertEqual(after_url, original_url)
        feed = await self.client.get("/s/" + after_url.rsplit("/", 1)[-1])
        self.assertEqual(feed.status_code, 200)

    async def test_native_expiry_worker_requests_revocation_without_refund(
        self,
    ):
        subscription, _, _, _ = await self.active_sale()
        sid = subscription["id"]
        disabled = await self.client.patch(
            f"/v1/admin/subscriptions/{sid}/auto-renew",
            headers=self.headers,
            json={"enabled": False},
        )
        self.assertEqual(disabled.status_code, 200)
        async with self.connection.uow() as independent:
            await independent.execute(
                update(SubscriptionTable)
                .where(col(SubscriptionTable.id) == sid)
                .values(
                    expires_at=datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(seconds=1)
                )
            )
            await independent.commit()
        from tests.scheduler_runtime import exercise_native_lifecycle

        observed = await asyncio.to_thread(
            exercise_native_lifecycle, self.raw, sid
        )
        self.assertEqual(observed, ("revoking", "expire"))
        ledger = await self.get(
            f"/v1/admin/payments/wallets/{subscription['customer_id']}/entries"
        )
        self.assertEqual(ledger["meta"]["pager"]["total_items"], 2)

    async def active_sale(self, mode="reserved"):
        subscription, request, nodes, purchase = await self.setup_sale(
            quota_policy={
                **self.raw["usage"]["policy"],
                "mode": mode,
                "grant_bytes": 600000000,
            }
        )
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        tasks = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"]
        claims = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        await asyncio.gather(
            *(
                self.ack(task, *claim)
                for task, claim in zip(tasks, claims, strict=True)
            )
        )
        return subscription, tasks, nodes, purchase

    def node_for(self, task, nodes):
        return next(
            node for node in nodes if node["node"]["id"] == task["node_id"]
        )

    async def allocate(self, task, nodes, amount, suffix="initial"):
        node = self.node_for(task, nodes)
        result = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/usage/grants",
            headers={"X-Papilio-Node-Key": node["agent_key"]},
            json={
                "profile_id": task["profile_id"],
                "generation": 0,
                "request_key": f"{self.suffix}_{suffix}",
                "requested_bytes": amount,
            },
        )
        return result

    async def usage(
        self,
        grant,
        task,
        nodes,
        upload,
        download,
        sequence=1,
        final=False,
        event_id=None,
        sampled_at=None,
    ):
        node = self.node_for(task, nodes)
        result = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/usage/grants/{grant['id']}/reports",
            headers={"X-Papilio-Node-Key": node["agent_key"]},
            json={
                "event_id": event_id
                or f"{self.suffix}_{grant['id']}_{sequence}",
                "sequence": sequence,
                "upload_bytes": upload,
                "download_bytes": download,
                "final": final,
                "sampled_at": (sampled_at or datetime.now(UTC)).isoformat(),
            },
        )
        return result

    async def test_reserved_quota_concurrency_and_timeout(
        self,
    ):
        subscription, tasks, nodes, _ = await self.active_sale()
        attempts = await asyncio.gather(
            *(self.allocate(task, nodes, 600000000) for task in tasks)
        )
        self.assertEqual(
            sorted(response.status_code for response in attempts), [200, 409]
        )
        winner = next(
            index
            for index, response in enumerate(attempts)
            if response.status_code == 200
        )
        first = attempts[winner].json()["data"]
        self.assertNotIn("request_key", first)
        self.assertEqual(
            datetime.fromisoformat(first["valid_until"]).utcoffset(),
            timedelta(0),
        )
        self.assertEqual(
            (
                await self.usage(
                    first, tasks[winner], nodes, 100000000, 50000000
                )
            ).status_code,
            200,
        )
        second = await self.allocate(tasks[1 - winner], nodes, 300000000)
        self.assertEqual(second.status_code, 200)
        async with self.connection.uow() as independent:
            rows = await independent.execute(
                select(UsageGrantTable).where(
                    col(UsageGrantTable.subscription_id) == subscription["id"]
                )
            )
            self.assertEqual(
                sum(row.allocated_bytes for row in rows.scalars()), 900000000
            )
            await independent.execute(
                update(UsageGrantTable)
                .where(col(UsageGrantTable.id) == first["id"])
                .values(
                    valid_until=datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(seconds=1)
                )
            )
            await independent.commit()
        expired = await self.allocate(
            tasks[winner], nodes, 500000000, "after_timeout"
        )
        self.assertEqual(expired.status_code, 409)
        finalized = await self.usage(
            first,
            tasks[winner],
            nodes,
            120000000,
            80000000,
            sequence=2,
            final=True,
        )
        self.assertEqual(finalized.status_code, 200)
        replacement = await self.allocate(
            tasks[winner], nodes, 500000000, "after_final"
        )
        self.assertEqual(replacement.status_code, 200)
        detail = (
            await self.get(f"/v1/admin/subscriptions/{subscription['id']}")
        )["data"]
        self.assertEqual(detail["used_bytes"], 200000000)
        excessive = await self.allocate(
            tasks[1 - winner], nodes, 600000000, "excess"
        )
        self.assertEqual(excessive.status_code, 409)

    async def test_usage_replay_counters_ownership_and_date_summary(
        self,
    ):
        subscription, tasks, nodes, _ = await self.active_sale("reported")
        grants = await asyncio.gather(
            *(self.allocate(task, nodes, 100000000) for task in tasks)
        )
        self.assertTrue(
            all(response.status_code == 200 for response in grants)
        )
        first, second = (response.json()["data"] for response in grants)
        at = datetime.now(UTC).replace(microsecond=0)
        event_id = "replay_" + self.suffix
        responses = await asyncio.gather(
            *(
                self.usage(
                    first,
                    tasks[0],
                    nodes,
                    120,
                    80,
                    event_id=event_id,
                    sampled_at=at,
                )
                for _ in range(2)
            )
        )
        self.assertTrue(
            all(response.status_code == 200 for response in responses)
        )
        self.assertEqual(
            responses[0].json()["data"]["id"],
            responses[1].json()["data"]["id"],
        )
        conflict = await self.usage(
            first, tasks[0], nodes, 121, 80, event_id=event_id, sampled_at=at
        )
        self.assertEqual(conflict.status_code, 409)
        decreasing = await self.usage(
            first, tasks[0], nodes, 119, 81, sequence=2
        )
        self.assertEqual(decreasing.status_code, 409)
        wrong_owner = await self.usage(
            first, tasks[1], nodes, 120, 80, sequence=2
        )
        self.assertEqual(wrong_owner.status_code, 404)
        self.assertEqual(
            (
                await self.usage(
                    second, tasks[1], nodes, 50, 25, sampled_at=at, final=True
                )
            ).status_code,
            200,
        )
        summary = (
            await self.get(
                f"/v1/admin/usage/summary?subscription_id={subscription['id']}&per_page=1"
            )
        )["data"]
        self.assertEqual(
            summary,
            {
                "upload_bytes": 170,
                "download_bytes": 105,
                "total_bytes": 275,
                "sample_count": 2,
            },
        )
        query = {
            "subscription_id": subscription["id"],
            "since": at.isoformat(),
            "until": at.isoformat(),
        }
        exact = await self.client.get("/v1/admin/usage/summary", params=query)
        self.assertEqual(exact.status_code, 200)
        self.assertEqual(exact.json()["data"]["total_bytes"], 275)
        first_page = await self.get(
            f"/v1/admin/usage/events?subscription_id={subscription['id']}&per_page=1"
        )
        self.assertEqual(first_page["meta"]["pager"]["total_items"], 2)
        self.assertNotIn("payload_hash", first_page["data"][0])
        detail = (
            await self.get(f"/v1/admin/subscriptions/{subscription['id']}")
        )["data"]
        self.assertEqual(detail["used_bytes"], 275)
        self.assertEqual(
            (
                await self.usage(second, tasks[1], nodes, 50, 26, sequence=2)
            ).status_code,
            409,
        )

    async def test_reserved_overrun_blocks_more_allocation(
        self,
    ):
        subscription, tasks, nodes, _ = await self.active_sale()
        grant = (await self.allocate(tasks[0], nodes, 100000000)).json()[
            "data"
        ]
        result = await self.usage(
            grant, tasks[0], nodes, 600000000, 400000001, final=True
        )
        self.assertEqual(result.status_code, 200)
        # The node violated its budget; actual consumption remains auditable.
        current = (
            await self.get(f"/v1/admin/subscriptions/{subscription['id']}")
        )["data"]
        self.assertEqual(current["used_bytes"], 1000000001)
        denied = await self.allocate(tasks[1], nodes, 1)
        self.assertEqual(denied.status_code, 409)
        wallet = (
            await self.get(
                f"/v1/admin/payments/wallets/{subscription['customer_id']}"
            )
        )["data"]
        self.assertEqual(wallet["balance_rial"], 200000)
