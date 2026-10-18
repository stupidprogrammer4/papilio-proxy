"""Owned funding keeps credit when effective purchased IP terms change."""

import asyncio
from uuid import uuid4

from tests.scheduler_runtime import _exercise_native_runtime
from tests.test_checkout_workflow import CheckoutWorkflowFixture


class CheckoutIpPolicyWorkflowTest(CheckoutWorkflowFixture):
    async def set_ip_defaults(self, maximum):
        current = (await self.get("/v1/admin/settings"))["data"]
        values = current["values"]
        values["ip_defaults"].update(enabled=True, max_ips=maximum)
        response = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={"expected_revision": current["revision"], "values": values},
        )
        self.assertEqual(response.status_code, 200, response.text)

    async def test_changed_ip_offer_preserves_credit_and_reconfirmed_n(
        self,
    ):
        await self.enable_manual_checkout()
        await self.set_ip_defaults(1)
        identity, headers, body, intent = await self.pending_intent("ip_offer")
        first = await self.client.post(
            f"/v1/bot/checkouts/offers/{body['plan_id']}",
            headers=headers,
            json=identity,
        )
        self.assertEqual(first.status_code, 200, first.text)
        initial = first.json()["data"]
        self.assertEqual(
            initial["effective_ip_policy"]["policy"]["max_ips"], 1
        )
        await self.set_ip_defaults(2)
        await self.post(
            f"/v1/admin/payments/topups/{intent['topup_id']}/approve",
            {
                "expected_revision": 1,
                "bank_reference": "ip_offer_" + self.suffix,
            },
        )
        sql = (
            "SELECT i.state,i.subscription_id,w.balance_rial,"
            "SUM(e.reason='purchase') debits,"
            "SUM(e.reason='approved_topup') credits "
            "FROM tbl_checkout_intents i JOIN tbl_wallets w "
            "ON w.customer_id=i.customer_id JOIN tbl_wallet_entries e "
            "ON e.wallet_id=w.id WHERE i.id=%s "
            "GROUP BY i.state,i.subscription_id,w.balance_rial"
        )
        held = await asyncio.to_thread(
            _exercise_native_runtime,
            self.raw,
            sql,
            (intent["id"],),
            lambda row: row["state"] == "action_required",
            ("state", "subscription_id", "balance_rial", "debits", "credits"),
            ("RecoverCheckout", "ScanCheckouts"),
            owned_namespace=self.checkout_namespace,
        )
        self.assertEqual(held, ("action_required", None, 120000, 0, 1))
        response = await self.client.post(
            f"/v1/bot/checkouts/{intent['id']}/status",
            headers=headers,
            json=identity,
        )
        self.assertEqual(response.status_code, 200, response.text)
        current = response.json()["data"]
        self.assertEqual(current["reason_code"], "checkout_offer_changed")
        response = await self.client.post(
            f"/v1/bot/checkouts/offers/{body['plan_id']}",
            headers=headers,
            json=identity,
        )
        self.assertEqual(response.status_code, 200, response.text)
        new_offer = response.json()["data"]
        self.assertNotEqual(new_offer["offer_sha256"], initial["offer_sha256"])
        self.assertEqual(new_offer["price_rial"], initial["price_rial"])
        self.assertEqual(
            new_offer["effective_ip_policy"]["policy"]["max_ips"], 2
        )
        reconfirm = {
            **identity,
            "request_key": "ip_reconfirm_" + uuid4().hex,
            "expected_revision": current["revision"],
            "expected_offer_sha256": new_offer["offer_sha256"],
            "expected_price_rial": new_offer["price_rial"],
        }
        response = await self.client.post(
            f"/v1/bot/checkouts/{intent['id']}/reconfirm",
            headers=headers,
            json=reconfirm,
        )
        self.assertEqual(response.status_code, 200, response.text)
        bought = await asyncio.to_thread(
            _exercise_native_runtime,
            self.raw,
            sql,
            (intent["id"],),
            lambda row: row["state"] == "purchased",
            ("state", "subscription_id", "balance_rial", "debits", "credits"),
            ("RecoverCheckout", "ScanCheckouts", "PrepareProvision"),
            owned_namespace=self.checkout_namespace,
        )
        self.assertEqual(bought[0], "purchased")
        self.assertEqual(bought[2:], (20000, 1, 1))
        subscription = (
            await self.get(f"/v1/admin/subscriptions/{bought[1]}")
        )["data"]
        self.assertEqual(
            subscription["purchased_ip_policy"]["policy"]["max_ips"], 2
        )
        replay = await self.client.post(
            "/v1/bot/checkouts", headers=headers, json=body
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["data"]["subscription_id"], bought[1])
