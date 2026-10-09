"""Native invoice amount identifiers and trusted declared-phone settlement."""

import asyncio
from contextvars import Context

from sqlalchemy import text

from src.modules.billing.payment_identifiers.domain.contracts import (
    PaymentIdentifierCapacity,
)
from tests.test_sms_origins_workflow import SmsOriginsWorkflowFixture


class SmsPaymentIdentifiersWorkflowTest(SmsOriginsWorkflowFixture):
    async def configure_identifiers(self, mode):
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
                "amount_step_rial": 1,
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
