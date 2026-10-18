import asyncio

import httpx
from sqlalchemy import text

from .test_ip_limit_workflow import IpLimitWorkflowFixture


class IpRefundPayerWorkflowTest(IpLimitWorkflowFixture):
    async def test_reseller_funded_refund_keeps_receiver_wallet_unchanged(
        self,
    ):
        organization = await self.post(
            "/v1/admin/resellers",
            {
                "code": "refund_" + self.suffix,
                "title": "Synthetic refund reseller",
                "owner": {
                    "username": "refund_" + self.suffix,
                    "password": "synthetic-refund-password",
                },
                "access": {
                    "login_enabled": True,
                    "sales_enabled": True,
                    "renewals_enabled": True,
                },
            },
        )
        reseller = organization["reseller"]
        capacity = self.settings.resellers
        assert capacity is not None
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url=capacity.portal_origin,
        ) as client:
            login = await client.post(
                "/v1/reseller/auth/login",
                headers={"Origin": capacity.portal_origin},
                json={
                    "username": organization["owner"]["username"],
                    "password": "synthetic-refund-password",
                },
            )
            self.assertEqual(login.status_code, 200)
            headers = {
                "Origin": capacity.portal_origin,
                "X-CSRF-Token": login.json()["csrf_token"],
            }
            buyer = await client.post(
                "/v1/reseller/customers",
                headers=headers,
                json={"display_name": "Synthetic receiver"},
            )
            self.assertEqual(buyer.status_code, 200)
            customer = buyer.json()["data"]
            plan = await self.post(
                "/v1/admin/plans",
                {
                    "code": "refund_" + self.suffix,
                    "title": "Synthetic reseller refund plan",
                    "quota_bytes": 1000000,
                    "duration_days": 30,
                    "price_rial": 100000,
                },
            )
            enabled = await self.client.patch(
                f"/v1/admin/plans/{plan['id']}/active",
                headers=self.headers,
                json={"is_active": True},
            )
            self.assertEqual(enabled.status_code, 200)
            await self.post(
                f"/v1/admin/resellers/{reseller['id']}/plans",
                {
                    "plan_id": plan["id"],
                    "enabled": True,
                    "price": {
                        "mode": "fixed",
                        "fixed_price_rial": 80000,
                        "rounding": "floor",
                        "quantum_rial": 10,
                    },
                    "reason": "Synthetic reseller agreement",
                },
            )
            payer_id = reseller["wallet_customer_id"]
            payer_topup, receiver_topup = await asyncio.gather(
                self.post(
                    "/v1/admin/payments/topups",
                    {
                        "customer_id": payer_id,
                        "amount_rial": 300000,
                    },
                ),
                self.post(
                    "/v1/admin/payments/topups",
                    {
                        "customer_id": customer["id"],
                        "amount_rial": 200000,
                    },
                ),
            )
            await asyncio.gather(
                self.post(
                    f"/v1/admin/payments/topups/{payer_topup['id']}/approve",
                    {
                        "expected_revision": 1,
                        "bank_reference": "payer_" + self.suffix,
                    },
                ),
                self.post(
                    f"/v1/admin/payments/topups/{receiver_topup['id']}/approve",
                    {
                        "expected_revision": 1,
                        "bank_reference": "receiver_" + self.suffix,
                    },
                ),
            )
            sale = await client.post(
                "/v1/reseller/subscriptions",
                headers=headers,
                json={
                    "customer_id": customer["id"],
                    "plan_id": plan["id"],
                    "payer_mode": "reseller_wallet",
                    "purchase_key": "refund_" + self.suffix,
                    "expected_price_rial": 80000,
                },
            )
            self.assertEqual(sale.status_code, 200)
            subscription = sale.json()["data"]
            self.assertEqual(subscription["payer_customer_id"], payer_id)
            id = subscription["id"]
            async with self.connection.uow() as fresh:
                before = await fresh.execute(
                    text(
                        "SELECT customer_id,balance_rial FROM tbl_wallets "
                        "WHERE customer_id IN (:payer,:receiver)"
                    ),
                    {"payer": payer_id, "receiver": customer["id"]},
                )
                self.assertEqual(
                    {row.customer_id: row.balance_rial for row in before},
                    {payer_id: 220000, customer["id"]: 200000},
                )
            refunded = await self.post(
                f"/v1/admin/subscriptions/{id}/provision-failed",
                {"reason": "Synthetic reseller provisioning failure"},
            )
            self.assertEqual(refunded["status"], "failed")
            await self.post(
                f"/v1/admin/subscriptions/{id}/provision-failed",
                {"reason": "Synthetic reseller provisioning failure"},
            )
            async with self.connection.uow() as fresh:
                balances = await fresh.execute(
                    text(
                        "SELECT customer_id,balance_rial FROM tbl_wallets "
                        "WHERE customer_id IN (:payer,:receiver)"
                    ),
                    {"payer": payer_id, "receiver": customer["id"]},
                )
                self.assertEqual(
                    {row.customer_id: row.balance_rial for row in balances},
                    {payer_id: 300000, customer["id"]: 200000},
                )
                refunds = await fresh.execute(
                    text(
                        "SELECT w.customer_id,e.amount_rial FROM tbl_walle"
                        "t_entries e "
                        "JOIN tbl_wallets w ON w.id=e.wallet_id "
                        "WHERE e.reference=:reference AND e.reason='provis"
                        "ion_refund'"
                    ),
                    {"reference": f"provision_refund:{id}:0"},
                )
                self.assertEqual(list(refunds), [(payer_id, 80000)])
