import asyncio
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from sqlalchemy import text

from src.modules.accounts.customer_auth.interfaces import ICustomerAuthCommand
from src.modules.sales.subscriptions.interfaces import ISubscriptionCommand
from tests.scheduler_runtime import (
    exercise_native_reseller_attention,
    exercise_native_reseller_renewal,
)
from tests.test_fulfillment_workflow import FulfillmentWorkflowFixture
from tests.test_reseller_catalog_workflow import ResellerCatalogWorkflowTest


class ResellerBillingWorkflowTest(
    ResellerCatalogWorkflowTest, FulfillmentWorkflowFixture
):
    async def acknowledge_tasks(self, request_id, nodes, outcome="applied"):
        tasks = (
            await self.get(
                f"/v1/admin/provisioning/{request_id}/tasks?per_page=100"
            )
        )["data"]
        claims = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        await asyncio.gather(
            *(
                self.ack(task, *claim, outcome=outcome)
                for task, claim in zip(tasks, claims, strict=True)
            )
        )
        return tasks

    async def renew(self, id):
        async with self.app.state.dishka_container() as scope:
            command = await scope.get(ISubscriptionCommand)
            result = await command.renew_due(id)
            return result.renewal_count

    async def fund(self, customer_id, amount_rial):
        topup = await self.post(
            "/v1/admin/payments/topups",
            {
                "customer_id": customer_id,
                "amount_rial": amount_rial,
            },
        )
        await self.post(
            f"/v1/admin/payments/topups/{topup['id']}/approve",
            {
                "bank_reference": "rb_" + uuid4().hex,
            },
        )

    async def customer_session(self, customer_id):
        async with self.app.state.dishka_container() as scope:
            auth = await scope.get(ICustomerAuthCommand)
            link = await auth.issue_link(customer_id)
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url=self.settings.public.customer_portal_origin,
        )
        result = await client.post(
            "/v1/customer/auth/exchange",
            json={"token": urlsplit(link.url).fragment},
            headers={"Origin": self.settings.public.customer_portal_origin},
        )
        self.assertEqual(result.status_code, 200)
        return client, {
            "Origin": self.settings.public.customer_portal_origin,
            "X-CSRF-Token": result.json()["csrf_token"],
        }

    async def test_payer_refund_replay_self_purchase_and_renewal_authority(
        self,
    ):
        organization = await self.organization()
        foreign = await self.organization()
        reseller = organization["reseller"]
        client, headers = await self.login_reseller(
            organization["owner"]["username"]
        )
        outsider, outside_headers = await self.login_reseller(
            foreign["owner"]["username"]
        )
        customer_client = None
        try:
            created = await client.post(
                "/v1/reseller/customers",
                headers=headers,
                json={
                    "display_name": "خریدار نمایندگی",
                    "telegram_id": int(self.suffix, 16) + 1,
                },
            )
            self.assertEqual(created.status_code, 200)
            customer = created.json()["data"]
            customer_client, customer_headers = await self.customer_session(
                customer["id"]
            )
            plan = await self.catalog_plan("billing")
            base = f"/v1/admin/resellers/{reseller['id']}/plans"
            agreement = await self.post(
                base,
                {
                    "plan_id": plan["id"],
                    "enabled": True,
                    "price": {
                        "mode": "fixed",
                        "fixed_price_rial": 80_000,
                        "rounding": "floor",
                        "quantum_rial": 10,
                    },
                    "reason": "قرارداد فروش نمایندگی",
                },
            )
            empty = await customer_client.get("/v1/customer/plans")
            self.assertEqual(empty.json()["meta"]["pager"]["total_items"], 0)
            forbidden_plan = await customer_client.get(
                f"/v1/customer/plans/{plan['id']}"
            )
            self.assertEqual(forbidden_plan.status_code, 409)
            await asyncio.gather(
                self.fund(reseller["wallet_customer_id"], 300_000),
                self.fund(customer["id"], 200_000),
            )
            body = {
                "customer_id": customer["id"],
                "plan_id": plan["id"],
                "payer_mode": "reseller_wallet",
                "purchase_key": uuid4().hex,
                "expected_price_rial": 80_000,
                "auto_renew": True,
            }
            blocked = await customer_client.post(
                "/v1/customer/subscriptions",
                headers=customer_headers,
                json={
                    **body,
                    "payer_customer_id": reseller["wallet_customer_id"],
                },
            )
            self.assertEqual(blocked.status_code, 409)
            wrong_owner = await outsider.post(
                "/v1/reseller/subscriptions",
                headers=outside_headers,
                json=body,
            )
            self.assertEqual(wrong_owner.status_code, 409)
            sold = await client.post(
                "/v1/reseller/subscriptions", headers=headers, json=body
            )
            self.assertEqual(sold.status_code, 200)
            sid = sold.json()["data"]["id"]
            self.assertEqual(
                sold.json()["data"]["payer_customer_id"],
                reseller["wallet_customer_id"],
            )
            self.assertNotIn("reseller_billing_json", sold.json()["data"])
            replay = await client.post(
                "/v1/reseller/subscriptions", headers=headers, json=body
            )
            self.assertEqual(replay.json()["data"]["id"], sid)
            changed_payer = await client.post(
                "/v1/reseller/subscriptions",
                headers=headers,
                json={**body, "payer_mode": "customer_wallet"},
            )
            self.assertEqual(changed_payer.status_code, 409)
            enabled = await customer_client.patch(
                f"/v1/customer/subscriptions/{sid}/auto-renew",
                headers=customer_headers,
                json={"enabled": True},
            )
            self.assertEqual(enabled.status_code, 409)
            disabled = await customer_client.patch(
                f"/v1/customer/subscriptions/{sid}/auto-renew",
                headers=customer_headers,
                json={"enabled": False},
            )
            self.assertEqual(disabled.status_code, 200)
            enabled_by_reseller = await client.patch(
                f"/v1/reseller/subscriptions/{sid}/auto-renew",
                headers=headers,
                json={"enabled": True},
            )
            self.assertEqual(enabled_by_reseller.status_code, 200)
            foreign_detail = await outsider.get(
                f"/v1/reseller/subscriptions/{sid}"
            )
            self.assertEqual(foreign_detail.status_code, 404)
            failed = await self.post(
                f"/v1/admin/subscriptions/{sid}/provision-failed",
                {"reason": "بازگشت خرید ناموفق"},
            )
            self.assertEqual(failed["status"], "failed")
            await self.post(
                f"/v1/admin/subscriptions/{sid}/provision-failed",
                {"reason": "بازگشت خرید ناموفق"},
            )
            async with self.connection.uow() as unit:
                row = (
                    await unit.execute(
                        text(
                            "SELECT payer_customer_id, reseller_id, "
                            "reseller_agreement_id "
                            "FROM tbl_subscriptions WHERE id=:id"
                        ),
                        {"id": sid},
                    )
                ).one()
                self.assertEqual(
                    tuple(row),
                    (
                        reseller["wallet_customer_id"],
                        reseller["id"],
                        agreement["id"],
                    ),
                )
                balances = (
                    await unit.execute(
                        text(
                            "SELECT customer_id, balance_rial "
                            "FROM tbl_wallets "
                            "WHERE customer_id IN (:payer,:receiver)"
                        ),
                        {
                            "payer": reseller["wallet_customer_id"],
                            "receiver": customer["id"],
                        },
                    )
                ).all()
                self.assertEqual(
                    {row.customer_id: row.balance_rial for row in balances},
                    {
                        reseller["wallet_customer_id"]: 300_000,
                        customer["id"]: 200_000,
                    },
                )
                effects = (
                    await unit.execute(
                        text(
                            "SELECT reason, COUNT(*) FROM tbl_wallet_entries "
                            "WHERE reason IN ('purchase','provision_refund') "
                            "GROUP BY reason"
                        )
                    )
                ).all()
                self.assertEqual(
                    {row.reason: row[1] for row in effects},
                    {"purchase": 1, "provision_refund": 1},
                )
            policy = {
                **reseller["policy"],
                "payer_mode": "either",
                "customer_self_purchase": True,
            }
            self.assertEqual(
                (await self.revise(reseller, policy=policy)).status_code, 200
            )
            catalog = await customer_client.get(
                "/v1/customer/plans?per_page=1"
            )
            self.assertEqual(catalog.json()["meta"]["pager"]["total_items"], 1)
            self.assertEqual(catalog.json()["data"][0]["price_rial"], 80_000)
            detail = await customer_client.get(
                f"/v1/customer/plans/{plan['id']}"
            )
            self.assertEqual(detail.json()["data"]["price_rial"], 80_000)
            bot_catalog = await self.client.post(
                "/v1/bot/customer-plans",
                json={
                    "telegram_id": customer["telegram_id"],
                    "display_name": customer["display_name"],
                },
                headers={
                    "X-Papilio-Bot-Key": self.settings.security.bot_service_key
                },
            )
            self.assertEqual(bot_catalog.status_code, 200)
            self.assertEqual(
                bot_catalog.json()["meta"]["pager"]["total_items"], 1
            )
            self.assertEqual(
                bot_catalog.json()["data"][0]["price_rial"], 80_000
            )
            direct = await customer_client.post(
                "/v1/customer/subscriptions",
                headers=customer_headers,
                json={
                    **body,
                    "purchase_key": uuid4().hex,
                    "auto_renew": False,
                },
            )
            self.assertEqual(direct.status_code, 200)
            direct_id = direct.json()["data"]["id"]
            self.assertNotIn("payer_customer_id", direct.json()["data"])
            self.assertNotIn("reseller_billing", direct.json()["data"])
            async with self.connection.uow() as unit:
                payer = (
                    await unit.execute(
                        text(
                            "SELECT payer_customer_id FROM tbl_subscriptions "
                            "WHERE id=:id"
                        ),
                        {"id": direct_id},
                    )
                ).scalar_one()
                self.assertEqual(payer, customer["id"])
            unassigned = await self.catalog_plan("unassigned")
            denied = await client.post(
                "/v1/reseller/subscriptions",
                headers=headers,
                json={
                    **body,
                    "purchase_key": uuid4().hex,
                    "plan_id": unassigned["id"],
                },
            )
            self.assertEqual(denied.status_code, 409)
        finally:
            await asyncio.gather(client.aclose(), outsider.aclose())
            if customer_client is not None:
                await customer_client.aclose()

    async def test_native_renewal_modes_and_uncertain_refund_to_original_payer(
        self,
    ):
        _, _, nodes, seed = await self.setup_sale(protocols=("vless_reality",))
        defaults = (await self.get("/v1/admin/resellers/defaults"))["data"]
        policy = {
            **defaults["policy"],
            "renewal_price_mode": "purchase_snapshot",
            "renewal_availability_mode": "purchase_snapshot",
        }
        organization = await self.organization(policy=policy)
        reseller = organization["reseller"]
        client, headers = await self.login_reseller(
            organization["owner"]["username"]
        )
        try:
            response = await client.post(
                "/v1/reseller/customers",
                headers=headers,
                json={"display_name": "تمدید نمایندگی"},
            )
            self.assertEqual(response.status_code, 200)
            customer = response.json()["data"]
            path = f"/v1/admin/resellers/{reseller['id']}/plans"
            pricing = {
                "mode": "fixed",
                "fixed_price_rial": 80_000,
                "rounding": "floor",
                "quantum_rial": 10,
            }
            agreement = await self.post(
                path,
                {
                    "plan_id": seed["plan_id"],
                    "enabled": True,
                    "price": pricing,
                    "reason": "تمدید قراردادی",
                },
            )
            await self.fund(reseller["wallet_customer_id"], 500_000)
            body = {
                "customer_id": customer["id"],
                "plan_id": seed["plan_id"],
                "payer_mode": "reseller_wallet",
                "auto_renew": True,
                "expected_price_rial": 80_000,
            }
            first = await client.post(
                "/v1/reseller/subscriptions",
                headers=headers,
                json={**body, "purchase_key": uuid4().hex},
            )
            self.assertEqual(first.status_code, 200)
            snapshot_id = first.json()["data"]["id"]
            current_policy = {
                **policy,
                "renewal_price_mode": "current_agreement",
                "renewal_availability_mode": "current_agreement",
            }
            self.assertEqual(
                (
                    await self.revise(reseller, policy=current_policy)
                ).status_code,
                200,
            )
            second = await client.post(
                "/v1/reseller/subscriptions",
                headers=headers,
                json={**body, "purchase_key": uuid4().hex},
            )
            self.assertEqual(second.status_code, 200)
            current_id = second.json()["data"]["id"]
            requests = await self.get(
                f"/v1/admin/provisioning?subscription_id={snapshot_id}"
            )
            snapshot_request = requests["data"][0]["id"]
            requests = await self.get(
                f"/v1/admin/provisioning?subscription_id={current_id}"
            )
            current_request = requests["data"][0]["id"]
            await asyncio.gather(
                *(
                    self.post(f"/v1/admin/provisioning/{id}/prepare")
                    for id in [snapshot_request, current_request]
                )
            )
            await asyncio.gather(
                self.acknowledge_tasks(snapshot_request, nodes),
                self.acknowledge_tasks(current_request, nodes),
            )
            async with self.connection.uow() as unit:
                await unit.execute(
                    text(
                        "UPDATE tbl_subscriptions SET expires_at=:past "
                        "WHERE id IN (:a,:b)"
                    ),
                    {
                        "past": datetime.now(UTC).replace(tzinfo=None)
                        - timedelta(seconds=1),
                        "a": snapshot_id,
                        "b": current_id,
                    },
                )
                await unit.commit()
            await asyncio.gather(
                *(
                    self.post(f"/v1/admin/subscriptions/{id}/check-lifecycle")
                    for id in [snapshot_id, current_id]
                )
            )
            await asyncio.gather(
                self.acknowledge_tasks(snapshot_request, nodes, "revoked"),
                self.acknowledge_tasks(current_request, nodes, "revoked"),
            )
            agreement_path = f"{path}/{agreement['id']}"
            revised_price = {**pricing, "fixed_price_rial": 110_000}
            off = await self.client.put(
                agreement_path,
                headers=self.headers,
                json={
                    "expected_revision": 1,
                    "enabled": False,
                    "price": revised_price,
                    "reason": "توقف قرارداد و تغییر قیمت",
                },
            )
            self.assertEqual(off.status_code, 200)
            self.assertEqual(await self.renew(current_id), 0)
            self.assertEqual(await self.renew(snapshot_id), 1)
            on = await self.client.put(
                agreement_path,
                headers=self.headers,
                json={
                    "expected_revision": 2,
                    "enabled": True,
                    "price": revised_price,
                    "reason": "ادامهٔ قرارداد",
                },
            )
            self.assertEqual(on.status_code, 200)
            result = await asyncio.to_thread(
                exercise_native_reseller_renewal, self.raw, current_id
            )
            self.assertEqual(result, (1,))
            self.assertEqual(await self.renew(current_id), 1)
            payer = (
                await self.get(
                    f"/v1/admin/payments/wallets/{reseller['wallet_customer_id']}"
                )
            )["data"]
            self.assertEqual(payer["balance_rial"], 150_000)
            receiver = (
                await self.get(f"/v1/admin/payments/wallets/{customer['id']}")
            )["data"]
            self.assertEqual(receiver["balance_rial"], 0)
            generations = await self.get(
                f"/v1/admin/provisioning?subscription_id={current_id}&per_page=100"
            )
            generation = next(
                row for row in generations["data"] if row["generation"] == 1
            )
            await self.post(
                f"/v1/admin/provisioning/{generation['id']}/prepare"
            )
            tasks = (
                await self.get(
                    f"/v1/admin/provisioning/{generation['id']}/tasks?per_page=100"
                )
            )["data"]
            old_claim = await self.claim(tasks[0], nodes)
            failed = await self.post(
                f"/v1/admin/subscriptions/{current_id}/provision-failed",
                {"reason": "خطای نامطمئن تمدید"},
            )
            self.assertEqual(failed["status"], "pending_provision")
            cancelling = (
                await self.get(
                    f"/v1/admin/provisioning?subscription_id={current_id}&per_page=100"
                )
            )["data"]
            self.assertEqual(
                next(
                    row["state"]
                    for row in cancelling
                    if row["generation"] == 1
                ),
                "revoking",
            )
            node, claim = old_claim
            stale = await self.client.post(
                f"/v1/nodes/{node['node']['code']}/provisioning/{tasks[0]['id']}/acknowledge",
                headers={"X-Papilio-Node-Key": node["agent_key"]},
                json={
                    "claim_token": claim["claim_token"],
                    "outcome": "applied",
                },
            )
            self.assertEqual(stale.status_code, 409)
            self.assertEqual(
                (
                    await self.get(
                        f"/v1/admin/payments/wallets/{reseller['wallet_customer_id']}"
                    )
                )["data"]["balance_rial"],
                150_000,
            )
            await self.acknowledge_tasks(generation["id"], nodes, "revoked")
            final = (await self.get(f"/v1/admin/subscriptions/{current_id}"))[
                "data"
            ]
            self.assertEqual(final["status"], "failed")
            await self.post(
                f"/v1/admin/subscriptions/{current_id}/provision-failed",
                {"reason": "بررسی تکرار بازگشت تمدید"},
            )
            async with self.connection.uow() as unit:
                balances = (
                    await unit.execute(
                        text(
                            "SELECT c.id AS customer_id, "
                            "COALESCE(w.balance_rial,0) AS balance_rial "
                            "FROM tbl_customers c LEFT JOIN tbl_wallets w "
                            "ON w.customer_id=c.id WHERE c.id IN (:a,:b)"
                        ),
                        {
                            "a": reseller["wallet_customer_id"],
                            "b": customer["id"],
                        },
                    )
                ).all()
                self.assertEqual(
                    {row.customer_id: row.balance_rial for row in balances},
                    {
                        reseller["wallet_customer_id"]: 260_000,
                        customer["id"]: 0,
                    },
                )
                effects = (
                    await unit.execute(
                        text(
                            "SELECT reason, COUNT(*) AS total "
                            "FROM tbl_wallet_entries "
                            "WHERE wallet_id=(SELECT id FROM tbl_wallets "
                            "WHERE customer_id=:id) "
                            "GROUP BY reason"
                        ),
                        {"id": reseller["wallet_customer_id"]},
                    )
                ).all()
                self.assertEqual(
                    {row.reason: row.total for row in effects},
                    {
                        "approved_topup": 1,
                        "purchase": 2,
                        "auto_renewal": 2,
                        "provision_refund": 1,
                    },
                )
        finally:
            await client.aclose()

    async def test_attention_uses_original_payer_and_current_agreement_quote(
        self,
    ):
        _, _, nodes, seed = await self.setup_sale(protocols=("vless_reality",))
        defaults = (await self.get("/v1/admin/resellers/defaults"))["data"]
        organization = await self.organization(
            policy={
                **defaults["policy"],
                "renewal_price_mode": "current_agreement",
                "renewal_availability_mode": "current_agreement",
            }
        )
        reseller = organization["reseller"]
        client, headers = await self.login_reseller(
            organization["owner"]["username"]
        )
        try:
            customer = (
                await client.post(
                    "/v1/reseller/customers",
                    headers=headers,
                    json={"display_name": "هشدار کیف پول پرداخت‌کننده"},
                )
            ).json()["data"]
            base = f"/v1/admin/resellers/{reseller['id']}/plans"
            pricing = {
                "mode": "fixed",
                "fixed_price_rial": 80000,
                "rounding": "floor",
                "quantum_rial": 10,
            }
            agreement = await self.post(
                base,
                {
                    "plan_id": seed["plan_id"],
                    "enabled": True,
                    "price": pricing,
                    "reason": "قرارداد هشدار",
                },
            )
            await self.fund(reseller["wallet_customer_id"], 180000)
            sale = await client.post(
                "/v1/reseller/subscriptions",
                headers=headers,
                json={
                    "customer_id": customer["id"],
                    "plan_id": seed["plan_id"],
                    "payer_mode": "reseller_wallet",
                    "purchase_key": uuid4().hex,
                    "expected_price_rial": 80000,
                    "auto_renew": True,
                },
            )
            self.assertEqual(sale.status_code, 200)
            sid = sale.json()["data"]["id"]
            request = (
                await self.get(f"/v1/admin/provisioning?subscription_id={sid}")
            )["data"][0]
            await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
            await self.acknowledge_tasks(request["id"], nodes)
            async with self.connection.uow() as unit:
                await unit.execute(
                    text(
                        "UPDATE tbl_subscriptions SET expires_at=:expiry "
                        "WHERE id=:id"
                    ),
                    {
                        "id": sid,
                        "expiry": datetime.now(UTC).replace(tzinfo=None)
                        + timedelta(minutes=5),
                    },
                )
                await unit.commit()
            revised = await self.client.put(
                f"{base}/{agreement['id']}",
                headers=self.headers,
                json={
                    "expected_revision": agreement["revision"],
                    "enabled": True,
                    "price": {**pricing, "fixed_price_rial": 110000},
                    "reason": "قیمت جاری تمدید",
                },
            )
            self.assertEqual(revised.status_code, 200)
            agreement = revised.json()["data"]
            checks = await asyncio.gather(
                *(
                    self.client.post(
                        f"/v1/admin/subscriptions/attention/{sid}/check",
                        headers=self.headers,
                    )
                    for _ in range(2)
                ),
                return_exceptions=True,
            )
            self.assertTrue(
                all(isinstance(result, httpx.Response) for result in checks),
                [type(result).__name__ for result in checks],
            )
            self.assertEqual(
                [
                    result.status_code
                    for result in checks
                    if isinstance(result, httpx.Response)
                ],
                [200, 200],
            )
            self.assertEqual(
                [
                    result.json()["data"]["status"]
                    for result in checks
                    if isinstance(result, httpx.Response)
                ],
                ["renewal_unfunded", "renewal_unfunded"],
            )
            rows = (
                await self.get(
                    f"/v1/admin/subscriptions/attention?customer_id={customer['id']}"
                )
            )["data"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(
                (
                    rows[0]["payer_customer_id"],
                    rows[0]["wallet_balance_rial"],
                    rows[0]["renewal_price_rial"],
                ),
                (reseller["wallet_customer_id"], 100000, 110000),
            )
            await self.fund(reseller["wallet_customer_id"], 10000)
            checked = await self.post(
                f"/v1/admin/subscriptions/attention/{sid}/check"
            )
            self.assertEqual(checked["status"], "expiry_soon")
            disabled = await self.client.put(
                f"{base}/{agreement['id']}",
                headers=self.headers,
                json={
                    "expected_revision": agreement["revision"],
                    "enabled": False,
                    "price": agreement["price"],
                    "reason": "توقف قرارداد تمدید",
                },
            )
            self.assertEqual(disabled.status_code, 200)
            async with self.connection.uow() as unit:
                await unit.execute(
                    text(
                        "UPDATE tbl_subscription_attention "
                        "SET checked_at=:old "
                        "WHERE subscription_id=:id"
                    ),
                    {"id": sid, "old": datetime(2000, 1, 1)},
                )
                await unit.commit()
            scheduled = await asyncio.to_thread(
                exercise_native_reseller_attention, self.raw, sid
            )
            self.assertEqual(
                scheduled,
                (
                    "renewal_unavailable",
                    reseller["wallet_customer_id"],
                    80000,
                    110000,
                ),
            )
            async with self.connection.uow() as unit:
                entries = (
                    await unit.execute(
                        text(
                            "SELECT reason,COUNT(*) FROM tbl_wallet_entries "
                            "GROUP BY reason"
                        )
                    )
                ).all()
                self.assertEqual(
                    {reason: count for reason, count in entries},
                    {"approved_topup": 3, "purchase": 2},
                )
                own_wallets = (
                    await unit.execute(
                        text(
                            "SELECT COUNT(*) FROM tbl_wallets "
                            "WHERE customer_id=:id"
                        ),
                        {"id": customer["id"]},
                    )
                ).scalar_one()
                self.assertEqual(own_wallets, 0)
        finally:
            await client.aclose()

    async def test_renewal_price_and_availability_modes_are_independent(self):
        _, _, nodes, seed = await self.setup_sale(protocols=("vless_reality",))
        defaults = (await self.get("/v1/admin/resellers/defaults"))["data"]

        async def sale(price_mode, availability_mode):
            organization = await self.organization(
                policy={
                    **defaults["policy"],
                    "renewal_price_mode": price_mode,
                    "renewal_availability_mode": availability_mode,
                }
            )
            reseller = organization["reseller"]
            client, headers = await self.login_reseller(
                organization["owner"]["username"]
            )
            try:
                customer = (
                    await client.post(
                        "/v1/reseller/customers",
                        headers=headers,
                        json={"display_name": "حالت مستقل تمدید"},
                    )
                ).json()["data"]
                await self.fund(reseller["wallet_customer_id"], 500000)
                agreement = await self.post(
                    f"/v1/admin/resellers/{reseller['id']}/plans",
                    {
                        "plan_id": seed["plan_id"],
                        "enabled": True,
                        "price": {
                            "mode": "fixed",
                            "fixed_price_rial": 80000,
                            "rounding": "floor",
                            "quantum_rial": 10,
                        },
                        "reason": "ثبت حالت مستقل قیمت و مجوز",
                    },
                )
                response = await client.post(
                    "/v1/reseller/subscriptions",
                    headers=headers,
                    json={
                        "customer_id": customer["id"],
                        "plan_id": seed["plan_id"],
                        "payer_mode": "reseller_wallet",
                        "purchase_key": uuid4().hex,
                        "expected_price_rial": 80000,
                        "auto_renew": True,
                    },
                )
                self.assertEqual(response.status_code, 200)
                sid = response.json()["data"]["id"]
                request = (
                    await self.get(
                        f"/v1/admin/provisioning?subscription_id={sid}"
                    )
                )["data"][0]
                await self.post(
                    f"/v1/admin/provisioning/{request['id']}/prepare"
                )
                await self.acknowledge_tasks(request["id"], nodes)
                revised = await self.client.put(
                    f"/v1/admin/resellers/{reseller['id']}/plans/{agreement['id']}",
                    headers=self.headers,
                    json={
                        "expected_revision": agreement["revision"],
                        "enabled": False,
                        "price": {
                            **agreement["price"],
                            "fixed_price_rial": 110000,
                        },
                        "reason": "توقف فروش و تغییر قیمت جاری",
                    },
                )
                self.assertEqual(revised.status_code, 200)
                return sid, request["id"], reseller["wallet_customer_id"]
            finally:
                await client.aclose()

        modes = await asyncio.gather(
            sale("purchase_snapshot", "purchase_snapshot"),
            sale("current_agreement", "purchase_snapshot"),
            sale("purchase_snapshot", "current_agreement"),
            sale("current_agreement", "current_agreement"),
        )
        async with self.connection.uow() as unit:
            await unit.execute(
                text(
                    "UPDATE tbl_subscriptions SET expires_at=:past "
                    "WHERE id IN (:first,:second,:third,:fourth)"
                ),
                {
                    "past": datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(seconds=1),
                    "first": modes[0][0],
                    "second": modes[1][0],
                    "third": modes[2][0],
                    "fourth": modes[3][0],
                },
            )
            await unit.commit()
        await asyncio.gather(
            *(
                self.post(f"/v1/admin/subscriptions/{sid}/check-lifecycle")
                for sid, _, _ in modes
            )
        )
        await asyncio.gather(
            *(
                self.acknowledge_tasks(request_id, nodes, "revoked")
                for _, request_id, _ in modes
            )
        )
        inactive = await self.client.patch(
            f"/v1/admin/plans/{seed['plan_id']}/active",
            headers=self.headers,
            json={"is_active": False},
        )
        self.assertEqual(inactive.status_code, 200)
        counts = await asyncio.gather(
            *(self.renew(sid) for sid, _, _ in modes)
        )
        self.assertEqual(counts, [1, 1, 0, 0])
        async with self.connection.uow() as unit:
            balances = (
                await unit.execute(
                    text(
                        "SELECT customer_id,balance_rial "
                        "FROM tbl_wallets WHERE customer_id IN "
                        "(:first,:second,:third,:fourth)"
                    ),
                    {
                        "first": modes[0][2],
                        "second": modes[1][2],
                        "third": modes[2][2],
                        "fourth": modes[3][2],
                    },
                )
            ).all()
            self.assertEqual(
                {payer: balance for payer, balance in balances},
                {
                    modes[0][2]: 340000,
                    modes[1][2]: 310000,
                    modes[2][2]: 420000,
                    modes[3][2]: 420000,
                },
            )
        self.assertEqual(await self.renew(modes[1][0]), 1)

    async def test_concurrent_wallet_credits_and_notifications_do_not_deadlock(
        self,
    ):
        organizations = await asyncio.gather(
            *(self.organization() for _ in range(4))
        )
        topups = await asyncio.gather(
            *(
                self.post(
                    "/v1/admin/payments/topups",
                    {
                        "customer_id": organization["reseller"][
                            "wallet_customer_id"
                        ],
                        "amount_rial": 125000,
                    },
                )
                for organization in organizations
            )
        )
        references = ["concurrent_" + uuid4().hex for _ in topups]
        approved = await asyncio.gather(
            *(
                self.client.post(
                    f"/v1/admin/payments/topups/{topup['id']}/approve",
                    headers=self.headers,
                    json={"bank_reference": reference},
                )
                for topup, reference in zip(topups, references, strict=True)
            ),
            return_exceptions=True,
        )
        self.assertTrue(
            all(isinstance(row, httpx.Response) for row in approved),
            [type(row).__name__ for row in approved],
        )
        self.assertEqual(
            [
                row.status_code
                for row in approved
                if isinstance(row, httpx.Response)
            ],
            [200] * 4,
        )
        replay = await asyncio.gather(
            *(
                self.client.post(
                    f"/v1/admin/payments/topups/{topup['id']}/approve",
                    headers=self.headers,
                    json={"bank_reference": reference},
                )
                for topup, reference in zip(topups, references, strict=True)
            )
        )
        self.assertEqual([row.status_code for row in replay], [200] * 4)
        async with self.connection.uow() as unit:
            balances = (
                (
                    await unit.execute(
                        text("SELECT balance_rial FROM tbl_wallets")
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(sorted(balances), [125000] * 4)
            effects = (
                await unit.execute(
                    text(
                        "SELECT (SELECT COUNT(*) FROM tbl_wallet_entries), "
                        "(SELECT COUNT(*) FROM tbl_notifications), "
                        "(SELECT COUNT(DISTINCT event_key) "
                        "FROM tbl_notifications), "
                        "(SELECT COUNT(*) FROM tbl_topups "
                        "WHERE status='approved')"
                    )
                )
            ).one()
            self.assertEqual(tuple(effects), (4, 4, 4, 4))
