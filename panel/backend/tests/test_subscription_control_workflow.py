import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlmodel import col

from src.modules.network.provisioning.infra.tables import ProvisionRequestTable
from src.modules.sales.subscriptions.infra.tables import (
    SubscriptionControlTable,
    SubscriptionTable,
)
from tests.test_fulfillment_workflow import FulfillmentWorkflowFixture


class SubscriptionControlWorkflowTest(FulfillmentWorkflowFixture):
    async def activated(self):
        subscription, request, nodes, _ = await self.setup_sale(
            failure_action="refund_wallet"
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
        subscription = (
            await self.get(f"/v1/admin/subscriptions/{subscription['id']}")
        )["data"]
        return subscription, request, tasks, nodes

    async def test_pause_final_usage_reapplication_replay_and_retained_balance(
        self,
    ):
        subscription, request, tasks, nodes = await self.activated()
        sid = subscription["id"]
        url = (
            await self.post(
                f"/v1/admin/network/configurations/subscriptions/{sid}/link"
            )
        )["url"]
        token = url.rsplit("/", 1)[-1]
        wallet_path = (
            f"/v1/admin/payments/wallets/{subscription['customer_id']}"
        )
        wallet = (await self.get(wallet_path))["data"]
        node = next(
            row for row in nodes if row["node"]["id"] == tasks[0]["node_id"]
        )
        node_headers = {"X-Papilio-Node-Key": node["agent_key"]}
        allocated = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/usage/grants",
            headers=node_headers,
            json={
                "profile_id": tasks[0]["profile_id"],
                "generation": 0,
                "request_key": "grant_" + self.suffix,
                "requested_bytes": 1000000,
            },
        )
        self.assertEqual(allocated.status_code, 200)
        grant = allocated.json()["data"]
        body = {
            "request_key": "suspend_" + self.suffix,
            "reason": "تعلیق به درخواست مشتری",
            "clock": "pause",
        }
        stopped = await self.client.put(
            f"/v1/admin/subscriptions/{sid}/suspension",
            headers=self.headers,
            json=body,
        )
        self.assertEqual(stopped.status_code, 200)
        self.assertEqual(stopped.json()["data"]["status"], "revoking")
        self.assertEqual(
            (await self.client.get(f"/s/{token}")).status_code, 404
        )
        resume_body = {
            "request_key": "resume_" + self.suffix,
            "reason": "ادامهٔ اشتراک",
        }
        pending = await self.client.put(
            f"/v1/admin/subscriptions/{sid}/resumption",
            headers=self.headers,
            json=resume_body,
        )
        self.assertEqual(pending.status_code, 409)
        claims = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        rejected = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/provisioning/{tasks[0]['id']}/acknowledge",
            headers=node_headers,
            json={
                "claim_token": claims[0][1]["claim_token"],
                "outcome": "revoked",
            },
        )
        self.assertEqual(rejected.status_code, 409)
        final = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/usage/grants/{grant['id']}/reports",
            headers=node_headers,
            json={
                "event_id": "final_" + self.suffix,
                "sequence": 1,
                "upload_bytes": 15,
                "download_bytes": 25,
                "sampled_at": datetime.now(UTC).isoformat(),
                "final": True,
            },
        )
        self.assertEqual(final.status_code, 200)
        await self.ack(tasks[0], *claims[0], outcome="revoked")
        self.assertEqual(
            (await self.get(f"/v1/admin/subscriptions/{sid}"))["data"][
                "status"
            ],
            "revoking",
        )
        await self.ack(tasks[1], *claims[1], outcome="revoked")
        current = (await self.get(f"/v1/admin/subscriptions/{sid}"))["data"]
        self.assertEqual(current["status"], "suspended")
        async with self.connection.uow() as unit:
            await unit.execute(
                update(SubscriptionTable)
                .where(col(SubscriptionTable.id) == sid)
                .values(
                    suspended_at=datetime.now(UTC).replace(
                        tzinfo=None, microsecond=0
                    )
                    - timedelta(hours=2)
                )
            )
            await unit.commit()
        resumed = await self.client.put(
            f"/v1/admin/subscriptions/{sid}/resumption",
            headers=self.headers,
            json=resume_body,
        )
        self.assertEqual(resumed.status_code, 200)
        row = resumed.json()["data"]
        self.assertEqual(row["status"], "pending_provision")
        self.assertEqual(row["used_bytes"], 40)
        self.assertEqual(row["renewal_count"], 0)
        original_expiry = datetime.fromisoformat(subscription["expires_at"])
        expiry = datetime.fromisoformat(row["expires_at"])
        self.assertGreaterEqual(
            (expiry - original_expiry).total_seconds(), 7200
        )
        self.assertLess((expiry - original_expiry).total_seconds(), 7205)
        replay = await self.client.put(
            f"/v1/admin/subscriptions/{sid}/resumption",
            headers=self.headers,
            json=resume_body,
        )
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(
            replay.json()["data"]["expires_at"], row["expires_at"]
        )
        refund = await self.client.post(
            f"/v1/admin/subscriptions/{sid}/provision-failed",
            headers=self.headers,
            json={"reason": "راه‌اندازی دوباره ناموفق"},
        )
        self.assertEqual(refund.status_code, 409)
        self.assertEqual(
            refund.json()["error"]["message_code"],
            "subscription_already_activated",
        )
        stale = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/provisioning/{tasks[0]['id']}/acknowledge",
            headers=node_headers,
            json={
                "claim_token": claims[0][1]["claim_token"],
                "outcome": "revoked",
            },
        )
        self.assertEqual(stale.status_code, 409)
        fresh = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        await self.ack(tasks[0], *fresh[0])
        self.assertEqual(
            (await self.get(f"/v1/admin/subscriptions/{sid}"))["data"][
                "status"
            ],
            "pending_provision",
        )
        await self.ack(tasks[1], *fresh[1])
        active = (await self.get(f"/v1/admin/subscriptions/{sid}"))["data"]
        self.assertEqual(active["status"], "active")
        self.assertEqual(active["expires_at"], row["expires_at"])
        self.assertEqual(
            (await self.client.get(f"/s/{token}")).status_code, 200
        )
        old_suspend = await self.client.put(
            f"/v1/admin/subscriptions/{sid}/suspension",
            headers=self.headers,
            json=body,
        )
        self.assertEqual(old_suspend.status_code, 200)
        self.assertEqual(old_suspend.json()["data"]["status"], "active")
        self.assertEqual((await self.get(wallet_path))["data"], wallet)
        records = await self.get(
            f"/v1/admin/subscriptions/{sid}/controls?per_page=1"
        )
        self.assertEqual(records["meta"]["pager"]["total_items"], 2)
        self.assertEqual(len(records["data"]), 1)
        self.assertEqual(records["data"][0]["action"], "resume")
        async with self.connection.uow() as independent:
            audits = (
                (
                    await independent.execute(
                        select(SubscriptionControlTable).where(
                            col(SubscriptionControlTable.subscription_id)
                            == sid
                        )
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(len(audits), 2)
            stored = (
                await independent.execute(
                    select(ProvisionRequestTable).where(
                        col(ProvisionRequestTable.id) == request["id"]
                    )
                )
            ).scalar_one()
            self.assertIn('"failure_action":"hold"', stored.policy_json)

    async def test_continuing_clock_rejects_expired_resume_without_charge(
        self,
    ):
        subscription, request, tasks, nodes = await self.activated()
        sid = subscription["id"]
        body = {
            "request_key": "continue_" + self.suffix,
            "reason": "تعلیق با ادامهٔ محاسبه",
            "clock": "continue",
        }
        stopped = await self.client.put(
            f"/v1/admin/subscriptions/{sid}/suspension",
            headers=self.headers,
            json=body,
        )
        self.assertEqual(stopped.status_code, 200)
        claims = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        await asyncio.gather(
            *(
                self.ack(task, *claim, outcome="revoked")
                for task, claim in zip(tasks, claims, strict=True)
            )
        )
        async with self.connection.uow() as unit:
            await unit.execute(
                update(SubscriptionTable)
                .where(col(SubscriptionTable.id) == sid)
                .values(
                    expires_at=datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(seconds=1)
                )
            )
            await unit.commit()
        failed = await self.client.put(
            f"/v1/admin/subscriptions/{sid}/resumption",
            headers=self.headers,
            json={
                "request_key": "expired_" + self.suffix,
                "reason": "ادامهٔ اشتراک",
            },
        )
        self.assertEqual(failed.status_code, 409)
        self.assertEqual(
            failed.json()["error"]["message_code"],
            "subscription_resume_consumed",
        )
        records = (await self.get(f"/v1/admin/subscriptions/{sid}/controls"))[
            "data"
        ]
        self.assertEqual(len(records), 1)
        self.assertEqual(
            (await self.get(f"/v1/admin/subscriptions/{sid}"))["data"][
                "status"
            ],
            "suspended",
        )
