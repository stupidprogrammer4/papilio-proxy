"""Native declared-phone settlement; generated SMS, no bank/OS attestation."""

import asyncio
import hashlib
import hmac
import json
import os
import time
from contextvars import Context
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pymysql
from papilio.api.application import create_app
from papilio.infra.db.transaction import transaction
from papilio_tasks.apps.lifecycle import Producers
from papilio_tasks.apps.schedulers.redis import create_app as tasks_app
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.engine import make_url

from src.config.providers import infrastructure_providers, task_providers
from src.config.settings import PapilioSettings
from src.modules.billing.sms_origins.domain.contracts import SmsOriginCapacity
from tests.lock_observation import MySQLLockObservation
from tests.scheduler_runtime import _exercise_native_runtime
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowFixture,
)


@dataclass(frozen=True, slots=True)
class DeviceExpiryObservation:
    dsn: str
    device_id: int


def wait_owned_device_expired(observation: DeviceExpiryObservation) -> None:
    """Wait for an observed database deadline, using a separate reader."""
    url = make_url(observation.dsn)
    with pymysql.connect(
        host=url.host or "127.0.0.1",
        port=url.port or 3306,
        user=url.username,
        password=url.password or "",
        database=url.database,
        autocommit=True,
        connect_timeout=5,
        read_timeout=5,
        write_timeout=5,
    ) as connection:
        deadline = time.monotonic() + 8
        with connection.cursor() as cursor:
            while time.monotonic() < deadline:
                cursor.execute(
                    "SELECT UTC_TIMESTAMP(6)>=expires_at FROM "
                    "tbl_sms_devices WHERE id=%s",
                    (observation.device_id,),
                )
                observed = cursor.fetchone()
                if observed is not None and observed[0] == 1:
                    return
                time.sleep(0.02)
    raise AssertionError("Owned SMS device database expiry was not observed")


class SmsOriginsWorkflowFixture(StaffAdministrationWorkflowFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        capacity = SmsOriginCapacity(
            enabled=True,
            page_size=10,
            max_page_size=50,
            max_profiles=10,
            max_profile_bytes=8192,
            max_rules_per_field=16,
            max_marker_chars=100,
            max_clauses=20,
            max_message_bytes=8192,
            max_realms=10,
            max_aliases_per_realm=10,
            max_match_candidates=20,
            original_timestamp_future_seconds=2,
            original_timestamp_max_age_seconds=3600,
        )
        self.settings.sms_origins = capacity
        self.raw["sms_origins"] = capacity.model_dump()

    async def receiving_source(self) -> dict[str, Any]:
        profile = await self.post(
            "/v1/admin/payments/sms-origins/parser-profiles",
            {
                "title": "Generated deposit format",
                "is_active": True,
                "definition": {
                    "mode": "labelled_credit",
                    "credit_markers": ["نشست"],
                    "debit_markers": ["برداشت"],
                    "clause_separators": ["\n"],
                    "deposit_relations": [
                        {
                            "marker": "به حساب شما نشست",
                            "relation": "amount_before_label",
                            "implicit_unit": None,
                        }
                    ],
                    "balance_relations": [
                        {
                            "marker": "موجودی:",
                            "relation": "label_before_amount",
                            "implicit_unit": None,
                        }
                    ],
                    "reference_labels": ["پیگیری"],
                    "rial_labels": ["ریال"],
                    "toman_labels": ["تومان"],
                    "grouping_separators": [",", "٬"],
                    "case_sensitive": True,
                },
            },
        )
        realm = await self.post(
            "/v1/admin/payments/sms-origins/receiving-realms",
            {
                "title": "Generated receiving account",
                "is_active": True,
                "origin_mode_enabled": True,
            },
        )
        self.assertIsNotNone(realm["origin_requirement_since_ms"])
        destination = await self.post(
            "/v1/admin/payments/destinations",
            {
                "title": "Generated account",
                "kind": "card",
                "account": "6037990000000001",
                "recipient": "Generated recipient",
                "bank_name": "Generated bank",
                "is_active": True,
            },
        )
        bound = await self.client.put(
            "/v1/admin/payments/sms-origins/destinations/"
            f"{destination['destination_id']}/receiving-account",
            headers=self.headers,
            json={
                "realm_id": realm["id"],
                "expected_realm_revision": realm["revision"],
                "expected_destination_revision": destination["revision"],
            },
        )
        self.assertEqual(bound.status_code, 200, bound.text)
        destination = bound.json()["data"]
        device_body = {
            "label": "Generated enrolled phone",
            "senders": ["GeneratedBank"],
            "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "is_active": True,
            "approval_mode": "unique_sms",
            "destination_id": destination["destination_id"],
            "parser_profile_id": profile["id"],
            "settlement_identity_mode": "trusted_origin_fingerprint",
        }
        enrolled = await self.post(
            "/v1/admin/payments/sms-devices", device_body
        )
        return {
            "profile": profile,
            "realm": realm,
            "destination": destination,
            "enrolled": enrolled,
            "device_body": device_body,
        }

    async def pending_topup(self, source, label):
        customer = await self.post(
            "/v1/admin/customers", {"display_name": "Generated " + label}
        )
        topup = await self.post(
            "/v1/admin/payments/topups",
            {
                "customer_id": customer["id"],
                "amount_rial": 120000,
                "destination_id": source["destination"]["destination_id"],
            },
        )
        return customer, topup

    def original_timestamp(self, source) -> int:
        timestamp = time.time_ns() // 1_000_000
        self.assertGreaterEqual(
            timestamp, source["realm"]["origin_requirement_since_ms"]
        )
        return timestamp

    async def upload_origin(
        self,
        enrollment,
        original_ms,
        event,
        *,
        original_sender="GeneratedBank",
        client=None,
        assert_accepted=True,
        message=(
            "آزمون عزیز، ۱۲۰٬۰۰۰ریال به حساب شما نشست.\n"
            "موجودی: ۹۰۰٬۰۰۰ ریال\n۱۹:۵۶"
        ),
    ):
        device_id = enrollment["device"]["id"]
        payload = {
            "event_id": event,
            "sender": "GeneratedBank",
            "message": message,
            "sent_at": (
                datetime(1970, 1, 1, tzinfo=UTC)
                + timedelta(milliseconds=original_ms)
            ).isoformat(),
            "origin": {
                "kind": "direct_sms",
                "original_provider_timestamp_ms": original_ms,
                "original_sender": original_sender,
                "canonicalization_revision": 1,
            },
        }
        raw = await asyncio.to_thread(json.dumps, payload)
        body = raw.encode()
        timestamp = str(int(time.time()))
        signing_key = enrollment["api_key"].encode()
        signing_input = f"{device_id}.{timestamp}.".encode() + body
        signature = await asyncio.to_thread(
            lambda: hmac.new(
                signing_key,
                signing_input,
                hashlib.sha256,
            ).hexdigest()
        )
        receiver = client if client is not None else self.client
        response = await receiver.post(
            f"/v1/webhooks/sms-devices/{device_id}",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Papilio-Timestamp": timestamp,
                "X-Papilio-Signature": signature,
            },
        )
        if assert_accepted:
            self.assertEqual(response.status_code, 200, response.text)
        return response

    async def financial_state(self, customer_id, topup_id):
        async with self.connection.uow() as fresh:
            state = await fresh.execute(
                text(
                    "SELECT t.status,t.bank_reference,t.approved_by_sms_id,"
                    "t.receiving_realm_id,t.receiving_alias_id,"
                    "(SELECT COALESCE(SUM(w.balance_rial),0) FROM "
                    "tbl_wallets w WHERE w.customer_id=t.customer_id) balance,"
                    "(SELECT COUNT(*) FROM tbl_wallet_entries e JOIN "
                    "tbl_wallets w ON w.id=e.wallet_id WHERE "
                    "w.customer_id=t.customer_id) entries,"
                    "(SELECT COUNT(*) FROM tbl_sms_settlements s WHERE "
                    "s.topup_id=t.id) settlements FROM tbl_topups t "
                    "WHERE t.id=:topup AND t.customer_id=:customer"
                ),
                {"topup": topup_id, "customer": customer_id},
            )
            result = dict(state.mappings().one())
        return result

    async def observed_id(self, event_id):
        async with self.connection.uow() as fresh:
            row = await fresh.execute(
                text("SELECT id FROM tbl_sms_events WHERE event_id=:event"),
                {"event": event_id},
            )
            id = row.scalar_one()
        return id


class SmsOriginsWorkflowTest(SmsOriginsWorkflowFixture):
    async def test_declared_origin_credit_replay_and_second_device_once(self):
        source = await self.receiving_source()
        customer, topup = await self.pending_topup(source, "first payer")
        original_ms = self.original_timestamp(source)
        event = "origin_first_" + self.suffix
        await self.upload_origin(source["enrolled"], original_ms, event)
        first = await self.financial_state(customer["id"], topup["id"])
        sms_id = await self.observed_id(event)
        review_path = (
            f"/v1/admin/payments/sms-origins/sms-events/{sms_id}/review"
        )
        approved_review = (await self.get(review_path))["data"]
        self.assertEqual(
            first["status"],
            "approved",
            f"Current review: {approved_review['status']}/"
            f"{approved_review['reason_code']}; "
            f"ledger={first['entries']}, balance={first['balance']}",
        )
        self.assertEqual((first["balance"], first["entries"]), (120000, 1))
        self.assertEqual(first["settlements"], 1)
        self.assertIsNone(first["bank_reference"])
        self.assertEqual(first["receiving_realm_id"], source["realm"]["id"])
        self.assertEqual(
            first["receiving_alias_id"],
            source["destination"]["receiving_alias_id"],
        )
        sms = (
            await self.get(
                f"/v1/admin/payments/sms/{first['approved_by_sms_id']}"
            )
        )["data"]
        self.assertEqual(sms["direction"], "credit")
        self.assertEqual(sms["amount_rial"], 120000)
        self.assertEqual(sms["balance_rial"], 900000)
        self.assertIsNone(sms["bank_reference"])
        self.assertEqual(
            sms["parser_revision_id"],
            source["profile"]["current_parser_revision_id"],
        )
        self.assertNotIn("message", sms)
        self.assertEqual(approved_review["status"], "approved")
        self.assertIsNone(approved_review["reason_code"])
        self.assertEqual(approved_review["topup_id"], topup["id"])
        self.assertIsNotNone(approved_review["settlement_id"])
        self.assertEqual(
            approved_review["evidence_kind"], "trusted_sms_origin"
        )
        self.assertIsNotNone(approved_review["checked_at"])
        self.assertFalse(approved_review["manual_approval_available"])
        await self.upload_origin(source["enrolled"], original_ms, event)
        self.assertEqual(
            first, await self.financial_state(customer["id"], topup["id"])
        )
        self.assertEqual(
            approved_review, (await self.get(review_path))["data"]
        )
        second_customer, second_topup = await self.pending_topup(
            source, "second payer"
        )
        second_device = await self.post(
            "/v1/admin/payments/sms-devices",
            {**source["device_body"], "label": "Second generated phone"},
        )
        await self.upload_origin(
            second_device, original_ms, "origin_other_device_" + self.suffix
        )
        second = await self.financial_state(
            second_customer["id"], second_topup["id"]
        )
        self.assertEqual(second["status"], "pending")
        self.assertEqual(
            (second["balance"], second["entries"], second["settlements"]),
            (0, 0, 0),
        )
        async with self.connection.uow() as fresh:
            claims = await fresh.execute(
                text(
                    "SELECT c.identity_kind FROM tbl_sms_settlement_claims c "
                    "JOIN tbl_sms_settlements s ON s.id=c.settlement_id "
                    "WHERE s.topup_id=:id ORDER BY c.identity_kind"
                ),
                {"id": topup["id"]},
            )
            kinds = claims.scalars().all()
            observations = await fresh.execute(
                text(
                    "SELECT id,origin_identity_sha256,"
                    "declared_notification_sha256 "
                    "FROM tbl_sms_events WHERE event_id IN (:first,:second) "
                    "ORDER BY id"
                ),
                {
                    "first": event,
                    "second": "origin_other_device_" + self.suffix,
                },
            )
            identities = observations.all()
        self.assertEqual(
            kinds, ["declared_notification", "trusted_sms_origin"]
        )
        self.assertEqual(len(identities), 2)
        self.assertIsNotNone(identities[0].origin_identity_sha256)
        self.assertIsNotNone(identities[0].declared_notification_sha256)
        self.assertEqual(
            identities[0].origin_identity_sha256,
            identities[1].origin_identity_sha256,
        )
        self.assertEqual(
            identities[0].declared_notification_sha256,
            identities[1].declared_notification_sha256,
        )
        repeated_review = (
            await self.get(
                "/v1/admin/payments/sms-origins/sms-events/"
                f"{identities[1].id}/review"
            )
        )["data"]
        self.assertEqual(repeated_review["status"], "manual")
        self.assertEqual(
            repeated_review["reason_code"], "sms_settlement_identity_used"
        )
        self.assertIsNone(repeated_review["settlement_id"])
        self.assertIsNone(repeated_review["evidence_kind"])

    async def test_debit_ambiguity_and_current_device_revoke_do_not_credit(
        self,
    ):
        source = await self.receiving_source()
        customer, first = await self.pending_topup(source, "ambiguous payer")
        other_customer, second = await self.pending_topup(
            source, "competing payer"
        )
        original_ms = self.original_timestamp(source)
        await self.upload_origin(
            source["enrolled"],
            original_ms,
            "origin_debit_" + self.suffix,
            message="برداشت۱۲۰٬۰۰۰ریال\nموجودی: ۹۰۰٬۰۰۰ ریال\n۱۹:۵۶",
        )
        event = "origin_ambiguous_" + self.suffix
        await self.upload_origin(source["enrolled"], original_ms, event)
        sms_id = await self.observed_id(event)
        review_path = (
            f"/v1/admin/payments/sms-origins/sms-events/{sms_id}/review"
        )
        ambiguous = (await self.get(review_path))["data"]
        self.assertEqual(ambiguous["status"], "ambiguous")
        self.assertEqual(ambiguous["reason_code"], "sms_topup_ambiguous")
        self.assertEqual(ambiguous["candidate_count"], 2)
        self.assertIsNone(ambiguous["settlement_id"])
        revoked = await self.client.put(
            f"/v1/admin/payments/sms-devices/{source['enrolled']['device']['id']}",
            headers=self.headers,
            json={
                **source["device_body"],
                "is_active": False,
                "expected_revision": source["enrolled"]["device"]["revision"],
            },
        )
        self.assertEqual(revoked.status_code, 200, revoked.text)
        current = await self.post(review_path + "/refresh")
        self.assertEqual(current["status"], "manual")
        self.assertEqual(
            current["reason_code"], "sms_receiving_binding_changed"
        )
        self.assertFalse(current["manual_approval_available"])
        self.assertEqual(current, (await self.get(review_path))["data"])
        first_state = await self.financial_state(customer["id"], first["id"])
        second_state = await self.financial_state(
            other_customer["id"], second["id"]
        )
        self.assertEqual(first_state["status"], "pending")
        self.assertEqual(second_state["status"], "pending")
        self.assertEqual(first_state["entries"] + second_state["entries"], 0)

    async def test_malformed_original_sender_is_durable_manual_without_credit(
        self,
    ):
        source = await self.receiving_source()
        customer, topup = await self.pending_topup(source, "untrusted sender")
        original_ms = self.original_timestamp(source)
        event = "origin_bad_sender_" + self.suffix
        # Observe HTTP rather than ASGI re-raising a server exception.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=self.app, raise_app_exceptions=False
            ),
            base_url="https://admin.example.com",
        ) as receiver:
            response = await self.upload_origin(
                source["enrolled"],
                original_ms,
                event,
                original_sender="\n",
                client=receiver,
                assert_accepted=False,
            )
        state = await self.financial_state(customer["id"], topup["id"])
        self.assertEqual(state["status"], "pending")
        self.assertEqual(
            (state["balance"], state["entries"], state["settlements"]),
            (0, 0, 0),
        )
        self.assertEqual(
            response.status_code,
            200,
            f"HTTP {response.status_code}; fresh pending payment, "
            "balance=0, ledger=0, settlements=0",
        )
        sms_id = await self.observed_id(event)
        sms = (await self.get(f"/v1/admin/payments/sms/{sms_id}"))["data"]
        self.assertEqual(
            sms["origin_reason_code"], "sms_original_sender_untrusted"
        )
        self.assertIsNone(sms["origin_identity_sha256"])
        self.assertIsNone(sms["declared_notification_sha256"])
        review = (
            await self.get(
                f"/v1/admin/payments/sms-origins/sms-events/{sms_id}/review"
            )
        )["data"]
        self.assertEqual(review["status"], "manual")
        self.assertEqual(
            review["reason_code"], "sms_original_sender_untrusted"
        )
        self.assertIsNone(review["settlement_id"])

    async def test_device_expiry_after_customer_wait_prevents_credit(self):
        source = await self.receiving_source()
        customer, topup = await self.pending_topup(source, "expiry payer")
        device_id = source["enrolled"]["device"]["id"]
        async with self.connection.uow() as fresh:
            clock = await fresh.execute(text("SELECT UTC_TIMESTAMP(6)"))
            expiry = clock.scalar_one().replace(tzinfo=UTC) + timedelta(
                seconds=4
            )
        edited = await self.client.put(
            f"/v1/admin/payments/sms-devices/{device_id}",
            headers=self.headers,
            json={
                **source["device_body"],
                "expires_at": expiry.isoformat(),
                "expected_revision": source["enrolled"]["device"]["revision"],
            },
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        original_ms = self.original_timestamp(source)
        event = "origin_expiry_wait_" + self.suffix
        delivery = None
        try:
            async with self.connection.uow() as holder:
                async with transaction(holder):
                    await holder.execute(
                        text(
                            "SELECT id FROM tbl_customers "
                            "WHERE id=:id FOR UPDATE"
                        ),
                        {"id": customer["id"]},
                    )
                    delivery = asyncio.create_task(
                        self.upload_origin(
                            source["enrolled"], original_ms, event
                        ),
                        context=Context(),
                    )
                    observed = await asyncio.to_thread(
                        MySQLLockObservation().wait_for_queries,
                        self.raw["db"]["dsn"],
                        "tbl_customers",
                        ("SELECT",),
                        1,
                        5.0,
                        0.02,
                        True,
                    )
                    self.assertTrue(observed, "Native Customer wait missing")
                    self.assertFalse(delivery.done())
                    await asyncio.to_thread(
                        wait_owned_device_expired,
                        DeviceExpiryObservation(
                            dsn=self.raw["db"]["dsn"], device_id=device_id
                        ),
                    )
                    self.assertFalse(delivery.done())
            await asyncio.wait_for(delivery, 8)
        finally:
            if delivery is not None:
                if not delivery.done():
                    delivery.cancel()
                await asyncio.gather(delivery, return_exceptions=True)
        state = await self.financial_state(customer["id"], topup["id"])
        sms_id = await self.observed_id(event)
        review = (
            await self.get(
                f"/v1/admin/payments/sms-origins/sms-events/{sms_id}/review"
            )
        )["data"]
        self.assertEqual(
            state["status"],
            "pending",
            f"Current review {review['status']}/{review['reason_code']}; "
            f"balance={state['balance']}, ledger={state['entries']}, "
            f"settlements={state['settlements']}",
        )
        self.assertEqual(
            (state["balance"], state["entries"], state["settlements"]),
            (0, 0, 0),
        )
        self.assertEqual(review["status"], "manual")
        self.assertEqual(
            review["reason_code"], "sms_receiving_binding_changed"
        )
        self.assertIsNone(review["settlement_id"])

    async def test_native_scanner_recovers_original_sms_before_topup(self):
        source = await self.receiving_source()
        original_ms = self.original_timestamp(source)
        await self.upload_origin(
            source["enrolled"], original_ms, "origin_early_" + self.suffix
        )
        customer, topup = await self.pending_topup(source, "late request")
        before = await self.financial_state(customer["id"], topup["id"])
        self.assertEqual((before["status"], before["entries"]), ("pending", 0))
        self.assertLessEqual(os.getloadavg()[0], 8)
        outcome = await asyncio.to_thread(
            _exercise_native_runtime,
            self.raw,
            "SELECT t.status,COUNT(s.id) settlements FROM tbl_topups t "
            "LEFT JOIN tbl_sms_settlements s ON s.topup_id=t.id "
            "WHERE t.id=%s GROUP BY t.id,t.status",
            (topup["id"],),
            lambda row: (
                row["status"] == "approved" and row["settlements"] == 1
            ),
            ("status", "settlements"),
            ("ScanPaymentReview", "CheckPaymentReview"),
        )
        self.assertEqual(outcome, ("approved", 1))
        after = await self.financial_state(customer["id"], topup["id"])
        self.assertEqual((after["balance"], after["entries"]), (120000, 1))
        self.assertIsNone(after["bank_reference"])

    async def test_manual_selection_revision_conflict_replay_and_disabled_read(
        self,
    ):
        source = await self.receiving_source()
        customer, topup = await self.pending_topup(source, "manual selected")
        other_customer, other_topup = await self.pending_topup(
            source, "manual competing"
        )
        original_ms = self.original_timestamp(source)
        event = "origin_manual_" + self.suffix
        await self.upload_origin(source["enrolled"], original_ms, event)
        sms_id = await self.observed_id(event)
        base = f"/v1/admin/payments/sms-origins/sms-events/{sms_id}"
        review = (await self.get(base + "/review"))["data"]
        self.assertEqual(review["status"], "ambiguous")
        self.assertTrue(review["manual_approval_available"])
        reason = "Owner confirmed generated ambiguous credit"
        approval = {
            "topup_id": topup["id"],
            "expected_device_revision": review["device_revision"],
            "expected_realm_revision": review["realm_revision"],
            "expected_destination_revision": review["destination_revision"],
            "reason": reason,
        }
        stale = await self.client.post(
            base + "/approve",
            headers=self.headers,
            json={
                **approval,
                "expected_device_revision": review["device_revision"] + 1,
            },
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertIn("sms_review_revision_conflict", stale.text)
        before = await self.financial_state(customer["id"], topup["id"])
        self.assertEqual((before["status"], before["entries"]), ("pending", 0))
        approved = await self.post(base + "/approve", approval)
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["topup_id"], topup["id"])
        self.assertEqual(approved["evidence_kind"], "trusted_sms_origin")
        self.assertFalse(approved["manual_approval_available"])
        committed = await self.financial_state(customer["id"], topup["id"])
        self.assertEqual(
            (
                committed["balance"],
                committed["entries"],
                committed["settlements"],
            ),
            (120000, 1, 1),
        )
        async with self.connection.uow() as fresh:
            stored = await fresh.execute(
                text(
                    "SELECT created_by_staff_id,review_reason FROM "
                    "tbl_sms_settlements WHERE topup_id=:id"
                ),
                {"id": topup["id"]},
            )
            provenance = stored.one()
        self.assertIsNotNone(provenance.created_by_staff_id)
        self.assertEqual(provenance.review_reason, reason)
        self.assertEqual(approved, (await self.get(base + "/review"))["data"])
        self.assertEqual(
            approved, await self.post(base + "/approve", approval)
        )
        other = await self.client.post(
            base + "/approve",
            headers=self.headers,
            json={**approval, "topup_id": other_topup["id"]},
        )
        self.assertEqual(other.status_code, 409, other.text)
        self.assertIn("sms_settlement_identity_used", other.text)
        self.settings.sms_origins = None
        self.assertEqual(approved, (await self.get(base + "/review"))["data"])
        self.assertEqual(
            approved, await self.post(base + "/approve", approval)
        )
        self.assertEqual(
            committed, await self.financial_state(customer["id"], topup["id"])
        )
        untouched = await self.financial_state(
            other_customer["id"], other_topup["id"]
        )
        self.assertEqual(untouched["status"], "pending")
        self.assertEqual(
            (
                untouched["balance"],
                untouched["entries"],
                untouched["settlements"],
            ),
            (0, 0, 0),
        )


class SmsOriginsCheckoutWorkflowFixture(SmsOriginsWorkflowFixture):
    async def configure_checkout_queue(self):
        self.raw["purchase_intents"] = {
            "policy": {
                "enabled": True,
                "admission_mode": "allow_manual_profiles",
                "default_expiry_seconds": 3600,
            },
            "scan_cron": "* * * * *",
            "recheck_seconds": 1,
        }
        self.checkout_namespace = "papilio:test:smscheckout:" + uuid4().hex
        self.raw["tasks"]["scheduler"].update(
            queue_name=self.checkout_namespace + ":jobs",
            schedule_prefix=self.checkout_namespace + ":schedules",
            result_prefix=self.checkout_namespace + ":results",
        )
        await self.client.aclose()
        await self.app.state.dishka_container.close()
        self.settings = PapilioSettings.model_validate(self.raw)
        native = tasks_app(
            self.settings.tasks.scheduler,
            providers=task_providers(self.settings),
            modules=self.settings.app.modules,
        )
        self.checkout_producers = Producers(native)
        await self.checkout_producers.connect()
        self.app = create_app(
            self.settings,
            providers=infrastructure_providers(self.settings),
            middleware=(),
            docs_url=None,
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="https://admin.example.com",
        )
        login = await self.client.post(
            "/v1/admin/auth/login",
            headers={"Origin": self.settings.public.admin_origin},
            json={"username": self.username, "password": self.password},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.headers = {
            "Origin": self.settings.public.admin_origin,
            "X-CSRF-Token": login.json()["csrf_token"],
        }
        prefs = (await self.get("/v1/admin/settings"))["data"]
        notices = prefs["values"]["notifications"]
        notices.update(
            enabled=True, channel_mode="inbox", delivery_enabled=False
        )
        notices["templates"]["payment_approved"]["enabled"] = True
        saved = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": prefs["revision"],
                "values": prefs["values"],
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)

    async def asyncTearDown(self):
        producers = getattr(self, "checkout_producers", None)
        if producers is not None:
            await producers.stop()
            redis = Redis.from_url(self.raw["redis"]["url"])
            try:
                # This fixture owns only its bounded, randomly named namespace.
                keys = await redis.keys(self.checkout_namespace + ":*")
                if keys:
                    await redis.delete(*keys)
            finally:
                await redis.aclose()
        await super().asyncTearDown()


class SmsOriginsCheckoutWorkflowTest(SmsOriginsCheckoutWorkflowFixture):
    async def test_manual_sms_same_queue_checkout_and_owned_inbox_once(self):
        await self.configure_checkout_queue()
        source = await self.receiving_source()
        identity = {
            "telegram_id": 6100000000 + int(self.suffix[:6], 16),
            "display_name": "Generated checkout payer",
        }
        bot_headers = {
            "X-Papilio-Bot-Key": self.settings.security.bot_service_key
        }
        plan = await self.post(
            "/v1/admin/plans",
            {
                "code": "smscheckout_" + self.suffix,
                "title": "Generated manually provisioned plan",
                "quota_bytes": 1000000000,
                "duration_days": 30,
                "price_rial": 100000,
            },
        )
        active = await self.client.patch(
            f"/v1/admin/plans/{plan['id']}/active",
            headers=self.headers,
            json={"is_active": True},
        )
        self.assertEqual(active.status_code, 200, active.text)
        offer_response = await self.client.post(
            f"/v1/bot/checkouts/offers/{plan['id']}",
            headers=bot_headers,
            json=identity,
        )
        self.assertEqual(offer_response.status_code, 200, offer_response.text)
        offer = offer_response.json()["data"]
        checkout_body = {
            **identity,
            "request_key": "smscheckout_" + uuid4().hex,
            "plan_id": plan["id"],
            "funding_mode": "approved_topup",
            "topup_amount_rial": 120000,
            "destination_id": source["destination"]["destination_id"],
            "expected_offer_sha256": offer["offer_sha256"],
            "expected_price_rial": offer["price_rial"],
            "auto_renew": False,
            "expiry_seconds": 3600,
            "changed_offer_action": "require_confirmation",
        }
        created = await self.client.post(
            "/v1/bot/checkouts", headers=bot_headers, json=checkout_body
        )
        self.assertEqual(created.status_code, 200, created.text)
        intent = created.json()["data"]
        self.assertEqual(intent["state"], "awaiting_funding")
        _, competing = await self.pending_topup(source, "competing checkout")
        event = "origin_checkout_" + self.suffix
        await self.upload_origin(
            source["enrolled"], self.original_timestamp(source), event
        )
        sms_id = await self.observed_id(event)
        base = f"/v1/admin/payments/sms-origins/sms-events/{sms_id}"
        review = (await self.get(base + "/review"))["data"]
        self.assertEqual(review["status"], "ambiguous")
        redis = Redis.from_url(self.raw["redis"]["url"])
        try:
            before = await redis.xlen(self.checkout_namespace + ":jobs")
            self.assertEqual(before, 1)
            approval_body = {
                "topup_id": intent["topup_id"],
                "expected_device_revision": review["device_revision"],
                "expected_realm_revision": review["realm_revision"],
                "expected_destination_revision": review[
                    "destination_revision"
                ],
                "reason": "Owner selected generated checkout payment",
            }
            approved = await self.post(base + "/approve", approval_body)
            self.assertEqual(approved["status"], "approved")
            self.assertEqual(approved["topup_id"], intent["topup_id"])
            self.assertEqual(
                await redis.xlen(self.checkout_namespace + ":jobs"), before + 1
            )
        finally:
            await redis.aclose()
        self.assertLessEqual(os.getloadavg()[0], 8)
        outcome = await asyncio.to_thread(
            _exercise_native_runtime,
            self.raw,
            "SELECT i.state,r.state provision_state,w.balance_rial,"
            "SUM(e.reason='purchase') debits,"
            "SUM(e.reason='approved_topup') credits,"
            "(SELECT COUNT(*) FROM tbl_notifications n WHERE "
            "n.customer_id=i.customer_id "
            "AND n.kind='payment_approved') notices "
            "FROM tbl_checkout_intents i JOIN tbl_subscriptions s "
            "ON s.id=i.subscription_id JOIN tbl_provision_requests r "
            "ON r.subscription_id=s.id JOIN tbl_wallets w "
            "ON w.customer_id=i.customer_id JOIN tbl_wallet_entries e "
            "ON e.wallet_id=w.id WHERE i.id=%s "
            "GROUP BY i.id,i.state,r.state,w.balance_rial",
            (intent["id"],),
            lambda row: (
                row["state"] == "purchased"
                and row["provision_state"] == "awaiting_profiles"
                and row["notices"] == 1
            ),
            (
                "state",
                "provision_state",
                "balance_rial",
                "debits",
                "credits",
                "notices",
            ),
            ("RecoverCheckout", "ScanCheckouts", "PrepareProvision"),
            owned_namespace=self.checkout_namespace,
        )
        self.assertEqual(
            outcome, ("purchased", "awaiting_profiles", 20000, 1, 1, 1)
        )
        replay = await self.client.post(
            "/v1/bot/checkouts", headers=bot_headers, json=checkout_body
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        purchased = replay.json()["data"]
        self.assertEqual(purchased["state"], "purchased")
        self.assertIsNotNone(purchased["subscription_id"])
        self.assertEqual(
            approved, await self.post(base + "/approve", approval_body)
        )
        customer_id = purchased["customer_id"]
        settled = await self.financial_state(customer_id, intent["topup_id"])
        self.assertEqual(
            (settled["balance"], settled["entries"], settled["settlements"]),
            (20000, 2, 1),
        )
        notices = await self.get(
            f"/v1/admin/notifications?customer_id={customer_id}&kind=payment_approved"
        )
        self.assertEqual(notices["meta"]["pager"]["total_items"], 1)
        notice = notices["data"][0]
        self.assertTrue(notice["inbox_visible"])
        self.assertEqual(notice["record_id"], intent["topup_id"])
        linked = await self.client.post(
            "/v1/bot/account-link", headers=bot_headers, json=identity
        )
        self.assertEqual(linked.status_code, 200, linked.text)
        token = linked.json()["data"]["url"].rsplit("#", 1)[-1]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url=self.settings.public.customer_portal_origin,
        ) as account:
            exchanged = await account.post(
                "/v1/customer/auth/exchange",
                headers={
                    "Origin": self.settings.public.customer_portal_origin
                },
                json={"token": token},
            )
            self.assertEqual(exchanged.status_code, 200)
            inbox = await account.get(
                "/v1/customer/notifications?kind=payment_approved"
            )
            self.assertEqual(inbox.status_code, 200, inbox.text)
            self.assertEqual(inbox.json()["meta"]["pager"]["total_items"], 1)
            self.assertEqual(inbox.json()["data"][0]["id"], notice["id"])
        async with self.connection.uow() as fresh:
            state = await fresh.execute(
                text("SELECT status FROM tbl_topups WHERE id=:id"),
                {"id": competing["id"]},
            )
            self.assertEqual(state.scalar_one(), "pending")
