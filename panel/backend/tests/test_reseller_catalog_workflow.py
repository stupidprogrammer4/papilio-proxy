import asyncio
from contextvars import Context

from sqlalchemy import text

from tests.test_reseller_accounts_workflow import ResellerAccountsWorkflowTest


class ResellerCatalogWorkflowTest(ResellerAccountsWorkflowTest):
    async def catalog_plan(self, suffix, price_rial=100_030):
        plan = await self.post(
            "/v1/admin/plans",
            {
                "code": "rp_" + suffix + "_" + self.suffix,
                "title": "پلن نمایندگی " + suffix,
                "quota_bytes": 1_073_741_824,
                "duration_days": 30,
                "price_rial": price_rial,
            },
        )
        activated = await self.client.patch(
            f"/v1/admin/plans/{plan['id']}/active",
            headers=self.headers,
            json={"is_active": True},
        )
        self.assertEqual(activated.status_code, 200)
        return plan

    async def test_quotes_revisions_availability_and_tenant_boundaries(self):
        organization = await self.organization()
        foreign = await self.organization()
        id = organization["reseller"]["id"]
        base = f"/v1/admin/resellers/{id}/plans"
        client, headers = await self.login_reseller(
            organization["owner"]["username"]
        )
        try:
            plans = await asyncio.gather(
                *(self.catalog_plan(str(index)) for index in range(4))
            )
            prices = [
                {"mode": "catalog", "rounding": "floor", "quantum_rial": 100},
                {
                    "mode": "fixed",
                    "fixed_price_rial": 20_025,
                    "rounding": "nearest",
                    "quantum_rial": 10,
                },
                {
                    "mode": "discount",
                    "discount_bps": 1250,
                    "rounding": "ceil",
                    "quantum_rial": 10,
                },
                {
                    "mode": "discount",
                    "discount_bps": 10_000,
                    "rounding": "floor",
                    "quantum_rial": 10,
                },
            ]
            agreements = await asyncio.gather(
                *(
                    self.post(
                        base,
                        {
                            "plan_id": plan["id"],
                            "enabled": True,
                            "price": price,
                            "reason": "ثبت قیمت قراردادی",
                        },
                    )
                    for plan, price in zip(plans, prices, strict=True)
                )
            )
            self.assertEqual(
                [row["price_rial"] for row in agreements],
                [100_000, 20_030, 87_530, 0],
            )
            page = await client.get("/v1/reseller/plans?per_page=1")
            self.assertEqual(page.status_code, 200)
            self.assertEqual(page.json()["meta"]["pager"]["total_items"], 4)
            self.assertEqual(len(page.json()["data"]), 1)
            second = await client.get("/v1/reseller/plans?page=2&per_page=1")
            self.assertNotEqual(
                page.json()["data"][0]["id"], second.json()["data"][0]["id"]
            )
            path = f"{base}/{agreements[0]['id']}"
            revised_price = {
                "mode": "fixed",
                "fixed_price_rial": 55_000,
                "rounding": "ceil",
                "quantum_rial": 10,
            }
            body = {
                "expected_revision": 1,
                "enabled": True,
                "price": revised_price,
                "reason": "اصلاح قیمت نمایندگی",
            }
            changed = await self.client.put(
                path, headers=self.headers, json=body
            )
            self.assertEqual(changed.status_code, 200)
            self.assertEqual(changed.json()["data"]["price_rial"], 55_000)
            stale = await self.client.put(
                path, headers=self.headers, json=body
            )
            self.assertEqual(stale.status_code, 409)
            history = await self.get(path + "/history?per_page=1")
            self.assertEqual(history["meta"]["pager"]["total_items"], 2)
            self.assertEqual(history["data"][0]["revision"], 2)
            denied = await self.client.get(
                f"/v1/admin/resellers/{foreign['reseller']['id']}/plans/"
                f"{agreements[0]['id']}/history"
            )
            self.assertEqual(denied.status_code, 404)
            dealer_edit = await client.put(path, headers=headers, json=body)
            self.assertEqual(dealer_edit.status_code, 401)
            duplicates = await self.client.post(
                base,
                headers=self.headers,
                json={
                    "plan_id": plans[0]["id"],
                    "enabled": True,
                    "price": prices[0],
                    "reason": "ثبت قرارداد تکراری",
                },
            )
            self.assertEqual(duplicates.status_code, 409)
            invalid = await self.client.post(
                base,
                headers=self.headers,
                json={
                    "plan_id": plans[0]["id"],
                    "enabled": True,
                    "price": {**prices[0], "discount_bps": 250},
                    "reason": "بررسی ورودی نامعتبر",
                },
            )
            self.assertEqual(invalid.status_code, 422)
            disabled = await self.client.put(
                path,
                headers=self.headers,
                json={
                    **body,
                    "expected_revision": 2,
                    "enabled": False,
                },
            )
            self.assertEqual(disabled.status_code, 200)
            inactive = await self.client.patch(
                f"/v1/admin/plans/{plans[1]['id']}/active",
                headers=self.headers,
                json={"is_active": False},
            )
            self.assertEqual(inactive.status_code, 200)
            available = await client.get("/v1/reseller/plans")
            self.assertEqual(
                available.json()["meta"]["pager"]["total_items"], 2
            )
            root_page = await self.get(base + "?per_page=10")
            self.assertEqual(root_page["meta"]["pager"]["total_items"], 4)
            changed_catalog = await self.client.patch(
                f"/v1/admin/plans/{plans[2]['id']}",
                headers=self.headers,
                json={"price_rial": 200_000},
            )
            self.assertEqual(changed_catalog.status_code, 200)
            quote = await self.get(f"{base}/{agreements[2]['id']}")
            self.assertEqual(quote["data"]["price_rial"], 175_000)
            async with self.connection.uow() as unit:
                counts = (
                    await unit.execute(
                        text(
                            "SELECT (SELECT COUNT(*) FROM tbl_reseller_plans),"
                            "(SELECT COUNT(*) FROM tbl_reseller_plan_changes),"
                            "(SELECT COUNT(*) FROM tbl_wallet_entries)"
                        )
                    )
                ).one()
                self.assertEqual(tuple(counts), (4, 6, 0))
        finally:
            await client.aclose()

    async def test_concurrent_plan_capacity_and_disable_recovery(self):
        defaults = (await self.get("/v1/admin/resellers/defaults"))["data"]
        organization = await self.organization(
            policy={**defaults["policy"], "plan_capacity": 1}
        )
        id = organization["reseller"]["id"]
        base = f"/v1/admin/resellers/{id}/plans"
        plans = await asyncio.gather(
            self.catalog_plan("one"), self.catalog_plan("two")
        )
        price = {"mode": "catalog", "rounding": "floor", "quantum_rial": 10}
        responses = await asyncio.gather(
            *(
                asyncio.create_task(
                    self.client.post(
                        base,
                        headers=self.headers,
                        json={
                            "plan_id": plan["id"],
                            "enabled": True,
                            "price": price,
                            "reason": "بررسی ظرفیت هم‌زمان",
                        },
                    ),
                    context=Context(),
                )
                for plan in plans
            )
        )
        self.assertEqual(
            sorted(row.status_code for row in responses), [200, 409]
        )
        accepted = next(
            row.json()["data"] for row in responses if row.status_code == 200
        )
        capacity = self.settings.resellers
        assert capacity is not None
        capacity.max_customers_per_reseller = 1
        path = f"{base}/{accepted['id']}"
        body = {
            "expected_revision": 1,
            "enabled": True,
            "price": price,
            "reason": "بررسی سقف کاهش‌یافته",
        }
        blocked = await self.client.put(path, headers=self.headers, json=body)
        self.assertEqual(blocked.status_code, 400)
        off = await self.client.put(
            path, headers=self.headers, json={**body, "enabled": False}
        )
        self.assertEqual(off.status_code, 200)
        async with self.connection.uow() as unit:
            rows = (
                await unit.execute(
                    text(
                        "SELECT enabled, revision FROM tbl_reseller_plans "
                        "WHERE reseller_id=:id"
                    ),
                    {"id": id},
                )
            ).all()
            self.assertEqual([tuple(row) for row in rows], [(0, 2)])
