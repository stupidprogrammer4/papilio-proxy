from papilio.infra.db.transaction import transaction
from sqlalchemy import select, update
from sqlmodel import col

from src.modules.sales.attention.infra.tables import SubscriptionAttentionTable
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowFixture,
)


class AttentionFiltersWorkflowTest(StaffAdministrationWorkflowFixture):
    async def test_exhausted_and_unavailable_filters_keep_customer(
        self,
    ):
        prefs = (await self.get("/v1/admin/settings"))["data"]
        prefs["values"]["fulfillment"]["renewal_price"] = "current_plan"
        saved = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": prefs["revision"],
                "values": prefs["values"],
            },
        )
        self.assertEqual(saved.status_code, 200)
        customer, subscription = await self.paid_subscription()
        async with self.connection.uow() as unit:
            async with transaction():
                await unit.execute(
                    update(SubscriptionTable)
                    .where(col(SubscriptionTable.id) == subscription["id"])
                    .values(
                        status="active", used_bytes=subscription["quota_bytes"]
                    )
                )
        checked = await self.post(
            f"/v1/admin/subscriptions/attention/{subscription['id']}/check"
        )
        self.assertEqual(checked["status"], "quota_exhausted")
        page = await self.client.get(
            "/v1/admin/subscriptions/attention",
            params={
                "status": "quota_exhausted",
                "customer_id": customer["id"],
                "per_page": 1,
            },
        )
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.json()["meta"]["pager"]["total_items"], 1)
        item = page.json()["data"][0]
        self.assertEqual(item["subscription_id"], subscription["id"])
        self.assertEqual(item["customer_id"], customer["id"])
        self.assertEqual(item["status"], "quota_exhausted")
        async with self.connection.uow() as independent:
            result = await independent.execute(
                select(SubscriptionAttentionTable).where(
                    col(SubscriptionAttentionTable.subscription_id)
                    == subscription["id"]
                )
            )
            self.assertEqual(result.scalar_one().status, "quota_exhausted")
        auto = await self.client.patch(
            f"/v1/admin/subscriptions/{subscription['id']}/auto-renew",
            headers=self.headers,
            json={"enabled": True},
        )
        self.assertEqual(auto.status_code, 200)
        disabled = await self.client.patch(
            f"/v1/admin/plans/{subscription['plan_id']}/active",
            headers=self.headers,
            json={"is_active": False},
        )
        self.assertEqual(disabled.status_code, 200)
        unavailable_check = await self.post(
            f"/v1/admin/subscriptions/attention/{subscription['id']}/check"
        )
        self.assertEqual(unavailable_check["status"], "renewal_unavailable")
        unavailable = await self.client.get(
            "/v1/admin/subscriptions/attention",
            params={
                "status": "renewal_unavailable",
                "customer_id": customer["id"],
                "per_page": 1,
            },
        )
        self.assertEqual(unavailable.status_code, 200)
        self.assertEqual(
            unavailable.json()["data"][0]["subscription_id"],
            subscription["id"],
        )
        self.assertFalse(unavailable.json()["data"][0]["renewal_available"])
        absent = await self.client.get(
            "/v1/admin/subscriptions/attention",
            params={
                "status": "quota_exhausted",
                "customer_id": customer["id"],
            },
        )
        self.assertEqual(absent.status_code, 200)
        self.assertEqual(absent.json()["meta"]["pager"]["total_items"], 0)
