"""Native invoice amount identifiers and trusted declared-phone settlement."""

import asyncio
import time
from contextvars import Context
from datetime import datetime, timedelta

from sqlalchemy import text

from src.modules.billing.payment_identifiers.domain.contracts import (
    PaymentIdentifierCapacity,
)
from tests.test_sms_origins_workflow import SmsOriginsWorkflowFixture


class SmsPaymentIdentifiersWorkflowTest(SmsOriginsWorkflowFixture):
    async def configure_identifiers(self, mode, amount_step_rial=1):
        self.settings.checkout.payment_identifier_capacity = (
            PaymentIdentifierCapacity(
                max_adjustment_rial=20,
                max_candidate_amounts=21,
                max_active_codes=10,
            )
        )
        preferences = (await self.get("/v1/admin/settings"))["data"]
        policy = preferences["values"]["checkout"]
        if policy is None:
            policy = self.settings.checkout.policy.model_dump(mode="json")
        policy["payment_identifier"] = (
            {
                "mode": mode,
                "max_adjustment_rial": 20,
                "amount_step_rial": amount_step_rial,
            }
            if mode is not None
            else None
        )
        preferences["values"]["checkout"] = policy
        saved = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": preferences["revision"],
                "values": preferences["values"],
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)

    async def payer(self, label):
        result = await self.post(
            "/v1/admin/customers",
            {"display_name": "Generated identifier " + label},
        )
        return result

    def invoice_body(self, source, customer, amount, key):
        return {
            "customer_id": customer["id"],
            "amount_rial": amount,
            "destination_id": source["destination"]["destination_id"],
            "request_key": key + "_" + self.suffix,
        }

    async def test_concurrent_same_base_unique_codes_replay_full_credit_once(
        self,
    ):
        await self.configure_identifiers("rial_suffix4")
        source = await self.receiving_source()
        first_customer = await self.payer("first")
        second_customer = await self.payer("second")
        requested = 130000
        first_body = self.invoice_body(
            source, first_customer, requested, "identifier_first"
        )
        second_body = self.invoice_body(
            source, second_customer, requested, "identifier_second"
        )
        first_task = asyncio.create_task(
            self.client.post(
                "/v1/admin/payments/topups",
                headers=self.headers,
                json=first_body,
            ),
            context=Context(),
        )
        second_task = asyncio.create_task(
            self.client.post(
                "/v1/admin/payments/topups",
                headers=self.headers,
                json=second_body,
            ),
            context=Context(),
        )
        first_response, second_response = await asyncio.gather(
            first_task, second_task
        )
        async with self.connection.uow() as fresh:
            issued = await fresh.execute(
                text(
                    "SELECT requested_amount_rial,amount_rial,"
                    "payment_identifier_code4,status FROM tbl_topups "
                    "WHERE customer_id IN (:first,:second) ORDER BY id"
                ),
                {
                    "first": first_customer["id"],
                    "second": second_customer["id"],
                },
            )
            issued_amounts = [tuple(row) for row in issued.all()]
            reservations = await fresh.execute(
                text(
                    "SELECT requested_amount_rial,payable_amount_rial,code4 "
                    "FROM tbl_payment_amount_reservations "
                    "WHERE receiving_realm_id=:realm ORDER BY id"
                ),
                {"realm": source["realm"]["id"]},
            )
            reserved_amounts = [tuple(row) for row in reservations.all()]
        self.assertEqual(
            first_response.status_code,
            200,
            f"Native invoices={issued_amounts}; "
            f"reservations={reserved_amounts}; "
            f"{first_response.text}",
        )
        self.assertEqual(
            second_response.status_code,
            200,
            f"Native invoices={issued_amounts}; "
            f"reservations={reserved_amounts}; "
            f"{second_response.text}",
        )
        first, second = (
            first_response.json()["data"],
            second_response.json()["data"],
        )
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["requested_amount_rial"], requested)
        self.assertEqual(second["requested_amount_rial"], requested)
        self.assertEqual(first["payment_identifier_mode"], "rial_suffix4")
        self.assertEqual(second["payment_identifier_mode"], "rial_suffix4")
        self.assertNotEqual(
            first["payment_identifier_code4"],
            second["payment_identifier_code4"],
        )
        self.assertEqual(
            {first["amount_rial"], second["amount_rial"]},
            {requested, requested + 1},
        )
        self.assertEqual(
            first["payment_identifier_code4"],
            f"{first['amount_rial'] % 10000:04d}",
        )
        self.assertEqual(
            second["payment_identifier_code4"],
            f"{second['amount_rial'] % 10000:04d}",
        )
        self.assertEqual(
            first, await self.post("/v1/admin/payments/topups", first_body)
        )
        self.assertEqual(
            second, await self.post("/v1/admin/payments/topups", second_body)
        )
        instructions = (
            await self.get(
                f"/v1/admin/payments/topups/{second['id']}/instruction"
            )
        )["data"]
        self.assertEqual(len(instructions), 1)
        instruction = instructions[0]
        self.assertEqual(instruction["topup_id"], second["id"])
        self.assertEqual(instruction["requested_amount_rial"], requested)
        self.assertEqual(
            instruction["payable_amount_rial"], second["amount_rial"]
        )
        self.assertEqual(
            instruction["payment_identifier_code4"],
            second["payment_identifier_code4"],
        )
        original_ms = self.original_timestamp(source)
        event = "identifier_credit_" + self.suffix
        message = (
            f"آزمون عزیز، {second['amount_rial']:,}ریال به حساب شما نشست.\n"
            "موجودی: ۹۰۰٬۰۰۰ ریال\n۱۹:۵۶"
        )
        await self.upload_origin(
            source["enrolled"], original_ms, event, message=message
        )
        settled = await self.financial_state(
            second_customer["id"], second["id"]
        )
        self.assertEqual(settled["status"], "approved")
        self.assertEqual(settled["balance"], second["amount_rial"])
        self.assertEqual((settled["entries"], settled["settlements"]), (1, 1))
        self.assertIsNone(settled["bank_reference"])
        untouched = await self.financial_state(
            first_customer["id"], first["id"]
        )
        self.assertEqual(untouched["status"], "pending")
        self.assertEqual((untouched["balance"], untouched["entries"]), (0, 0))
        await self.upload_origin(
            source["enrolled"], original_ms, event, message=message
        )
        self.assertEqual(
            settled,
            await self.financial_state(second_customer["id"], second["id"]),
        )
        self.assertEqual(
            (await self.post("/v1/admin/payments/topups", second_body))[
                "amount_rial"
            ],
            second["amount_rial"],
        )
        sms_id = await self.observed_id(event)
        review = (
            await self.get(
                f"/v1/admin/payments/sms-origins/sms-events/{sms_id}/review"
            )
        )["data"]
        self.assertEqual(review["status"], "approved")
        self.assertEqual(review["topup_id"], second["id"])
        self.assertEqual(review["evidence_kind"], "trusted_sms_origin")

    async def test_aliases_share_realm_reservations_and_invoice_snapshots(
        self,
    ):
        await self.configure_identifiers("rial_suffix4")
        source = await self.receiving_source()
        second_destination = await self.post(
            "/v1/admin/payments/destinations",
            {
                "title": "Generated second receiving alias",
                "kind": "card",
                "account": "6037990000000002",
                "recipient": "Generated recipient",
                "bank_name": "Generated bank",
                "is_active": True,
            },
        )
        second_binding = await self.client.put(
            "/v1/admin/payments/sms-origins/destinations/"
            f"{second_destination['destination_id']}/receiving-account",
            headers=self.headers,
            json={
                "realm_id": source["realm"]["id"],
                "expected_realm_revision": source["realm"]["revision"],
                "expected_destination_revision": second_destination[
                    "revision"
                ],
            },
        )
        self.assertEqual(second_binding.status_code, 200, second_binding.text)
        second_destination = second_binding.json()["data"]
        first_customer = await self.payer("shared-realm-first")
        second_customer = await self.payer("shared-realm-second")
        requested = 130000
        first = await self.post(
            "/v1/admin/payments/topups",
            self.invoice_body(source, first_customer, requested, "shared_a"),
        )
        second = await self.post(
            "/v1/admin/payments/topups",
            {
                "customer_id": second_customer["id"],
                "amount_rial": requested,
                "destination_id": second_destination["destination_id"],
                "request_key": "shared_b_" + self.suffix,
            },
        )
        self.assertEqual(
            {first["amount_rial"], second["amount_rial"]},
            {requested, requested + 1},
        )
        self.assertNotEqual(
            first["payment_identifier_code4"],
            second["payment_identifier_code4"],
        )

        other_realm = await self.post(
            "/v1/admin/payments/sms-origins/receiving-realms",
            {
                "title": "Generated other receiving account",
                "is_active": True,
                "origin_mode_enabled": True,
            },
        )
        duplicate_account = await self.post(
            "/v1/admin/payments/destinations",
            {
                "title": "Generated duplicate account",
                "kind": "card",
                "account": "6037990000000001",
                "recipient": "Generated recipient",
                "bank_name": "Generated bank",
                "is_active": True,
            },
        )
        rejected = await self.client.put(
            "/v1/admin/payments/sms-origins/destinations/"
            f"{duplicate_account['destination_id']}/receiving-account",
            headers=self.headers,
            json={
                "realm_id": other_realm["id"],
                "expected_realm_revision": other_realm["revision"],
                "expected_destination_revision": duplicate_account["revision"],
            },
        )
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertIn("sms_receiving_alias_realm_conflict", rejected.text)

        changed = await self.client.put(
            f"/v1/admin/payments/destinations/"
            f"{second_destination['destination_id']}",
            headers=self.headers,
            json={
                "expected_revision": second_destination["revision"],
                "title": second_destination["title"],
                "kind": "card",
                "account": "6037990000000003",
                "recipient": second_destination["recipient"],
                "bank_name": second_destination["bank_name"],
                "instructions": second_destination["instructions"],
                "is_active": True,
            },
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        changed_destination = changed.json()["data"]
        self.assertIsNone(changed_destination["receiving_alias_id"])
        rebound = await self.client.put(
            "/v1/admin/payments/sms-origins/destinations/"
            f"{changed_destination['destination_id']}/receiving-account",
            headers=self.headers,
            json={
                "realm_id": other_realm["id"],
                "expected_realm_revision": other_realm["revision"],
                "expected_destination_revision": changed_destination[
                    "revision"
                ],
            },
        )
        self.assertEqual(rebound.status_code, 200, rebound.text)
        future_customer = await self.payer("future-realm")
        future = await self.post(
            "/v1/admin/payments/topups",
            {
                "customer_id": future_customer["id"],
                "amount_rial": requested,
                "destination_id": changed_destination["destination_id"],
                "request_key": "shared_future_" + self.suffix,
            },
        )
        self.assertEqual(future["amount_rial"], requested)
        async with self.connection.uow() as fresh:
            snapshots = await fresh.execute(
                text(
                    "SELECT receiving_realm_id,receiving_alias_id,amount_rial "
                    "FROM tbl_topups WHERE id IN (:first,:second,:future) "
                    "ORDER BY id"
                ),
                {
                    "first": first["id"],
                    "second": second["id"],
                    "future": future["id"],
                },
            )
            captured = [tuple(row) for row in snapshots.all()]
        self.assertEqual(
            captured,
            [
                (
                    source["realm"]["id"],
                    source["destination"]["receiving_alias_id"],
                    first["amount_rial"],
                ),
                (
                    source["realm"]["id"],
                    second_destination["receiving_alias_id"],
                    second["amount_rial"],
                ),
                (
                    other_realm["id"],
                    rebound.json()["data"]["receiving_alias_id"],
                    future["amount_rial"],
                ),
            ],
        )

    async def test_late_sms_cannot_settle_a_new_invoice_with_same_amount(self):
        await self.configure_identifiers(None)
        source = await self.receiving_source()
        expired_customer = await self.payer("expired-invoice")
        expired = await self.post(
            "/v1/admin/payments/topups",
            self.invoice_body(source, expired_customer, 120000, "late_old"),
        )
        current_ms = time.time_ns() // 1_000_000
        event_ms = max(
            source["realm"]["origin_requirement_since_ms"] + 1000,
            current_ms - 5000,
        )
        later_customer = await self.payer("later-invoice")
        later = await self.post(
            "/v1/admin/payments/topups",
            self.invoice_body(source, later_customer, 120000, "late_new"),
        )
        event_at = datetime(1970, 1, 1) + timedelta(milliseconds=event_ms)
        async with self.connection.uow() as unit:
            await unit.execute(
                text("UPDATE tbl_topups SET status='expired' WHERE id=:id"),
                {"id": expired["id"]},
            )
            await unit.execute(
                text("UPDATE tbl_topups SET created_at=:created WHERE id=:id"),
                {
                    "created": event_at + timedelta(seconds=3),
                    "id": later["id"],
                },
            )
            await unit.commit()
        event = "late_same_amount_" + self.suffix
        await self.upload_origin(source["enrolled"], event_ms, event)
        later_state = await self.financial_state(
            later_customer["id"], later["id"]
        )
        expired_state = await self.financial_state(
            expired_customer["id"], expired["id"]
        )
        self.assertEqual(later_state["status"], "pending")
        self.assertEqual(
            (later_state["balance"], later_state["entries"]), (0, 0)
        )
        self.assertEqual(expired_state["status"], "expired")
        self.assertEqual(
            (expired_state["balance"], expired_state["entries"]), (0, 0)
        )

    async def test_whole_toman_channel_keeps_exact_rial_invoice_amounts(self):
        await self.configure_identifiers("rial_suffix4", amount_step_rial=10)
        source = await self.receiving_source()
        customer = await self.payer("whole-toman-channel")
        requested = 130001
        invoice = await self.post(
            "/v1/admin/payments/topups",
            self.invoice_body(source, customer, requested, "whole_toman"),
        )
        self.assertEqual(invoice["requested_amount_rial"], requested)
        self.assertEqual(invoice["amount_rial"], 130010)
        self.assertEqual(invoice["amount_rial"] % 10, 0)
        instructions = (
            await self.get(
                f"/v1/admin/payments/topups/{invoice['id']}/instruction"
            )
        )["data"]
        self.assertEqual(len(instructions), 1)
        instruction = instructions[0]
        self.assertEqual(instruction["requested_amount_rial"], requested)
        self.assertEqual(instruction["payable_amount_rial"], 130010)
        self.assertEqual(instruction["payment_identifier_code4"], "0010")
        original_ms = self.original_timestamp(source)
        same_code_amount = (
            f"آزمون عزیز، {140010:,}ریال به حساب شما نشست.\n"
            "موجودی: ۹۰۰٬۰۰۰ ریال\n۱۹:۵۶"
        )
        await self.upload_origin(
            source["enrolled"],
            original_ms,
            "same_suffix_wrong_amount_" + self.suffix,
            message=same_code_amount,
        )
        pending = await self.financial_state(customer["id"], invoice["id"])
        self.assertEqual(
            (pending["status"], pending["balance"], pending["entries"]),
            ("pending", 0, 0),
        )
        actual_amount = (
            f"آزمون عزیز، {130010:,}ریال به حساب شما نشست.\n"
            "موجودی: ۹۰۰٬۰۰۰ ریال\n۱۹:۵۶"
        )
        await self.upload_origin(
            source["enrolled"],
            original_ms,
            "whole_toman_exact_amount_" + self.suffix,
            message=actual_amount,
        )
        settled = await self.financial_state(customer["id"], invoice["id"])
        self.assertEqual(settled["status"], "approved")
        self.assertEqual(settled["balance"], 130010)
        self.assertEqual((settled["entries"], settled["settlements"]), (1, 1))

    async def test_melli_positive_suffix_credit_and_debit_replay(self):
        await self.configure_identifiers("rial_suffix4")
        source = await self.receiving_source()
        changed = await self.client.put(
            f"/v1/admin/payments/sms-origins/parser-profiles/{source['profile']['id']}",
            headers=self.headers,
            json={
                "expected_revision": source["profile"]["revision"],
                "title": "Generated Melli credit format",
                "is_active": True,
                "definition": {
                    "mode": "labelled_credit",
                    "credit_markers": ["انتقال:"],
                    "debit_markers": ["برداشت"],
                    "clause_separators": [" ", "\n"],
                    "deposit_relations": [
                        {
                            "marker": "انتقال:",
                            "relation": "label_before_amount",
                            "implicit_unit": "rial",
                            "required_amount_suffix": "+",
                        }
                    ],
                    "balance_relations": [
                        {
                            "marker": "مانده:",
                            "relation": "label_before_amount",
                            "implicit_unit": "rial",
                        }
                    ],
                    "reference_labels": ["پیگیری:"],
                    "rial_labels": ["ریال"],
                    "toman_labels": ["تومان"],
                    "grouping_separators": [","],
                    "case_sensitive": True,
                },
            },
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        first_customer = await self.payer("Melli pending")
        customer = await self.payer("Melli matched")
        first = await self.post(
            "/v1/admin/payments/topups",
            self.invoice_body(source, first_customer, 130000, "melli_first"),
        )
        topup = await self.post(
            "/v1/admin/payments/topups",
            self.invoice_body(source, customer, 130000, "melli_second"),
        )
        self.assertNotEqual(first["amount_rial"], topup["amount_rial"])
        original_ms = self.original_timestamp(source)
        debit = (
            f"بانك ملي ايران انتقال:{topup['amount_rial']:,}- "
            "حساب:00001 مانده:774,587 0527-18:26"
        )
        await self.upload_origin(
            source["enrolled"],
            original_ms,
            "melli_debit_" + self.suffix,
            message=debit,
        )
        pending = await self.financial_state(customer["id"], topup["id"])
        self.assertEqual(
            (pending["status"], pending["balance"], pending["entries"]),
            ("pending", 0, 0),
        )
        event = "melli_credit_" + self.suffix
        credit = (
            f"بانك ملي ايران انتقال:{topup['amount_rial']:,}+ "
            "حساب:00001 مانده:774,587 0527-18:26"
        )
        await self.upload_origin(
            source["enrolled"], original_ms, event, message=credit
        )
        settled = await self.financial_state(customer["id"], topup["id"])
        self.assertEqual(settled["status"], "approved")
        self.assertEqual(settled["balance"], topup["amount_rial"])
        self.assertEqual((settled["entries"], settled["settlements"]), (1, 1))
        await self.upload_origin(
            source["enrolled"], original_ms, event, message=credit
        )
        self.assertEqual(
            settled, await self.financial_state(customer["id"], topup["id"])
        )
        untouched = await self.financial_state(
            first_customer["id"], first["id"]
        )
        self.assertEqual(
            (untouched["status"], untouched["balance"], untouched["entries"]),
            ("pending", 0, 0),
        )

    async def test_normal_amounts_after_identifier_mode_off(
        self,
    ):
        await self.configure_identifiers("rial_suffix4")
        source = await self.receiving_source()
        customer = await self.payer("protected history")
        body = self.invoice_body(source, customer, 130000, "protected_first")
        issued = await self.post("/v1/admin/payments/topups", body)
        original_ms = self.original_timestamp(source)
        event = "identifier_old_credit_" + self.suffix
        message = (
            f"آزمون عزیز، {issued['amount_rial']:,}ریال به حساب شما نشست.\n"
            "موجودی: ۹۰۰٬۰۰۰ ریال\n۱۹:۵۶"
        )
        await self.upload_origin(
            source["enrolled"], original_ms, event, message=message
        )
        settled = await self.financial_state(customer["id"], issued["id"])
        self.assertEqual(settled["status"], "approved")
        pending_body = self.invoice_body(
            source, customer, 140001, "protected_pending"
        )
        pending = await self.post("/v1/admin/payments/topups", pending_body)
        await self.configure_identifiers(None)
        self.settings.checkout.payment_identifier_capacity = None
        historical = await self.client.post(
            "/v1/admin/payments/topups",
            headers=self.headers,
            json=self.invoice_body(
                source, customer, issued["amount_rial"], "historical_reuse"
            ),
        )
        self.assertEqual(historical.status_code, 200, historical.text)
        self.assertEqual(
            historical.json()["data"]["amount_rial"], issued["amount_rial"]
        )
        self.assertIsNone(
            historical.json()["data"]["payment_identifier_code4"]
        )
        code_collision = await self.client.post(
            "/v1/admin/payments/topups",
            headers=self.headers,
            json=self.invoice_body(
                source,
                customer,
                pending["amount_rial"] + 10000,
                "pending_code_reuse",
            ),
        )
        self.assertEqual(code_collision.status_code, 200, code_collision.text)
        ordinary = code_collision.json()["data"]
        self.assertEqual(
            ordinary["amount_rial"], pending["amount_rial"] + 10000
        )
        self.assertEqual(
            ordinary["payment_identifier_mode"], "exact_requested"
        )
        self.assertIsNone(ordinary["payment_identifier_code4"])
        await self.configure_identifiers("exact_requested")
        repeat = await self.post(
            "/v1/admin/payments/topups",
            self.invoice_body(
                source, customer, ordinary["amount_rial"], "ordinary_repeat"
            ),
        )
        self.assertNotEqual(repeat["id"], ordinary["id"])
        self.assertEqual(repeat["amount_rial"], ordinary["amount_rial"])
        self.assertIsNone(repeat["payment_identifier_code4"])
        async with self.connection.uow() as fresh:
            count = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_payment_amount_reservations "
                    "WHERE receiving_realm_id=:realm"
                ),
                {"realm": source["realm"]["id"]},
            )
            self.assertEqual(count.scalar_one(), 2)
        replay = await self.post("/v1/admin/payments/topups", body)
        self.assertEqual(replay["id"], issued["id"])
        self.assertEqual(replay["amount_rial"], issued["amount_rial"])
        self.assertEqual(
            replay["payment_identifier_code4"],
            issued["payment_identifier_code4"],
        )
        await self.upload_origin(
            source["enrolled"], original_ms, event, message=message
        )
        self.assertEqual(
            settled, await self.financial_state(customer["id"], issued["id"])
        )
