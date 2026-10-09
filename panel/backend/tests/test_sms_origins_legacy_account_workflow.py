"""Unbound invoices cannot borrow the current alias bank identity."""

from tests.test_sms_origins_workflow import SmsOriginsWorkflowFixture


class SmsOriginsLegacyAccountWorkflowTest(SmsOriginsWorkflowFixture):
    async def test_legacy_account_never_borrows_current_bank_namespace(
        self,
    ):
        source = await self.receiving_source()
        destination_id = source["destination"]["destination_id"]
        legacy = await self.client.put(
            f"/v1/admin/payments/destinations/{destination_id}",
            headers=self.headers,
            json={
                "expected_revision": source["destination"]["revision"],
                "title": "Generated old receiving account",
                "kind": "bank_account",
                "account": "800000001",
                "recipient": "Generated recipient",
                "bank_name": "Generated old bank display label",
                "instructions": None,
                "is_active": True,
            },
        )
        self.assertEqual(legacy.status_code, 200, legacy.text)
        source["destination"] = legacy.json()["data"]
        self.assertIsNone(source["destination"]["receiving_alias_id"])
        customer, topup = await self.pending_topup(source, "unbound account")
        before = await self.financial_state(customer["id"], topup["id"])
        self.assertIsNone(before["receiving_realm_id"])
        self.assertIsNone(before["receiving_alias_id"])

        # The captured instruction has only an editable display label, not
        # an immutable bank namespace. Mapping that number later cannot prove
        # which bank the original invoice belonged to.
        bound = await self.client.put(
            "/v1/admin/payments/sms-origins/destinations/"
            f"{destination_id}/receiving-account",
            headers=self.headers,
            json={
                "realm_id": source["realm"]["id"],
                "expected_realm_revision": source["realm"]["revision"],
                "expected_destination_revision": source["destination"][
                    "revision"
                ],
                "bank_namespace": "generated-new-stable-bank",
            },
        )
        self.assertEqual(bound.status_code, 200, bound.text)
        source["destination"] = bound.json()["data"]
        event = "legacy_bank_namespace_" + self.suffix
        # An observation-only intake is not enough to obtain a financial
        # candidate projection. The signed enrolled origin takes the real
        # native command path; its correct outcome remains no credit.
        await self.upload_origin(
            source["enrolled"], self.original_timestamp(source), event
        )
        sms_id = await self.observed_id(event)
        state = await self.financial_state(customer["id"], topup["id"])
        response = await self.get(
            "/v1/admin/payments/sms-origins/sms-events/"
            f"{sms_id}/candidates?page=1&per_page=10"
        )
        self.assertEqual(len(response["data"]), 1)
        candidate = response["data"][0]
        failures = []
        if candidate["association_kind"] != "unresolved":
            failures.append("legacy bank namespace was inferred")
        if candidate["selectable"]:
            failures.append("unproved receiving bank was selectable")
        if state["status"] != "pending":
            failures.append("unproved invoice was approved")
        if (state["balance"], state["entries"], state["settlements"]) != (
            0,
            0,
            0,
        ):
            failures.append("unproved bank-account association credited money")
        self.assertEqual(failures, [], "; ".join(failures))
