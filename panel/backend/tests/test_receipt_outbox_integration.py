import asyncio
import base64
import json
import os
from io import BytesIO
from types import SimpleNamespace
from typing import cast
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

import nats
import yaml
from alembic import command
from alembic.config import Config
from faststream.nats import NatsBroker as NativeNatsBroker
from nats.js.errors import NotFoundError
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.security.crypto import decrypt, encrypt
from papilio_tasks.apps.events.application import create_app as events_app
from papilio_tasks.apps.events.registry.jetstream import JetRegistrar
from papilio_tasks.infra.faststream.brokers.backends.nats import NatsBroker
from PIL import Image
from sqlalchemy import func, select, text, update
from sqlmodel import col

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.domain.models import CustomerModel
from src.modules.accounts.customers.infra.mysql import CustomerRepository
from src.modules.billing.receipts.app.commands import PaymentReceiptCommand
from src.modules.billing.receipts.app.images import ReceiptImages
from src.modules.billing.receipts.app.ocr_commands import (
    PaymentReceiptOcrCommand,
)
from src.modules.billing.receipts.app.ocr_interfaces import IReceiptOcrApi
from src.modules.billing.receipts.domain.dtos import ReceiptPolicy
from src.modules.billing.receipts.domain.events import ReceiptOcrRequest
from src.modules.billing.receipts.domain.extraction import (
    ReceiptExtractionFields,
    ReceiptOcrLine,
    ReceiptOcrResult,
)
from src.modules.billing.receipts.domain.models import PaymentReceiptModel
from src.modules.billing.receipts.infra.mysql import (
    PaymentReceiptOutboxRepository,
    PaymentReceiptRepository,
)
from src.modules.billing.receipts.infra.outbox_tables import (
    ReceiptOcrOutboxTable,
)
from src.modules.billing.receipts.infra.tables import PaymentReceiptTable
from src.modules.billing.receipts.tasks.events import (
    ReceiptOcrConsumer,
    ReceiptOcrRequested,
)
from src.modules.billing.wallet.app.topups import TopupRecordService
from src.modules.billing.wallet.domain.models import TopupModel
from src.modules.billing.wallet.infra.mysql import TopupRepository
from src.modules.operations.preferences.interfaces import IPreferencesService

TEST_DATABASE_URL = os.getenv("PAPILIO_TEST_DATABASE_URL")
REDIS_TEST_URL = os.getenv("PAPILIO_TEST_REDIS_URL")
NATS_TEST_URL = os.getenv("NATS_TEST_URL")


def configured_settings() -> PapilioSettings:
    with open("config.yml.sample", encoding="utf-8") as source:
        raw = yaml.safe_load(source)
    raw["db"]["dsn"] = TEST_DATABASE_URL
    raw["db"]["test_dsn"] = TEST_DATABASE_URL
    raw["rate_limit"]["enabled"] = False
    raw["events"]["nats_url"] = NATS_TEST_URL
    return PapilioSettings.model_validate(raw)


@skipUnless(
    TEST_DATABASE_URL and REDIS_TEST_URL and NATS_TEST_URL,
    "Requires isolated MySQL, Redis, and NATS test services",
)
class ReceiptOutboxIntegrationTest(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        migration = Config("alembic.ini")
        migration.set_main_option("sqlalchemy.url", str(TEST_DATABASE_URL))
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(command.upgrade, migration, "head")
        settings = configured_settings()
        assert settings.db is not None
        self.connection = DBConnection(
            dsn=settings.db.dsn,
            pool_size=3,
            max_overflow=0,
            pool_timeout=10,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )

    async def asyncTearDown(self) -> None:
        await self.connection.dispose()

    async def test_committed_outbox_claim_recovers_and_publishes_once(self):
        suffix = uuid4().hex
        content_hash = suffix[:64]
        async with self.connection.uow() as unit:
            await unit.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            async with unit.transaction():
                receipt = await PaymentReceiptRepository(unit).create(
                    PaymentReceiptModel(
                        topup_id=2_000_000_000,
                        content_hash=content_hash,
                        media_type="image/jpeg",
                        size_bytes=1,
                        encrypted_payload="test-only-ciphertext",
                    )
                )
                await PaymentReceiptOutboxRepository(unit).ensure_pending(
                    receipt.id
                )
            await unit.execute(text("SET FOREIGN_KEY_CHECKS=1"))

        try:
            async with self.connection.uow() as independent:
                found = await independent.execute(
                    select(ReceiptOcrOutboxTable).where(
                        col(ReceiptOcrOutboxTable.receipt_id) == receipt.id
                    )
                )
                self.assertEqual(found.scalar_one().status, "pending")

            claims = await asyncio.gather(self._claim(), self._claim())
            self.assertEqual(sum(claim is not None for claim in claims), 1)
            first_claim = next(claim for claim in claims if claim is not None)
            self.assertEqual(first_claim.receipt_id, receipt.id)

            async with self.connection.uow() as unit:
                async with unit.transaction():
                    await unit.execute(
                        update(ReceiptOcrOutboxTable)
                        .where(
                            col(ReceiptOcrOutboxTable.id)
                            == first_claim.outbox_id
                        )
                        .values(
                            lease_until=func.timestampadd(
                                text("SECOND"), -1, func.utc_timestamp()
                            )
                        )
                    )

            retry_durable = "receipt-outbox-" + suffix[:16]
            broker = NatsBroker(NativeNatsBroker(str(NATS_TEST_URL)))
            registrar = JetRegistrar(broker)
            registrar.publisher(ReceiptOcrRequested)
            publisher_app = events_app(registrar=registrar)
            await publisher_app.start()
            client = await nats.connect(str(NATS_TEST_URL))
            try:
                jetstream = client.jetstream()
                await jetstream.purge_stream(ReceiptOcrRequested.stream.name)
                subscription = await jetstream.pull_subscribe(
                    ReceiptOcrRequested.subject,
                    durable=retry_durable,
                    stream=ReceiptOcrRequested.stream.name,
                )
                from tests.scheduler_runtime import (
                    exercise_native_receipt_outbox,
                )

                delivered = await asyncio.to_thread(
                    exercise_native_receipt_outbox,
                    str(TEST_DATABASE_URL),
                    str(REDIS_TEST_URL),
                    str(NATS_TEST_URL),
                    first_claim.outbox_id,
                )
                self.assertEqual(delivered, ("published", 2))

                messages = await subscription.fetch(1, timeout=5)
                message = next(iter(messages))
                event = json.loads(message.data)
                self.assertEqual(event["receipt_id"], receipt.id)
                await message.ack()
            finally:
                try:
                    await client.jetstream().delete_consumer(
                        ReceiptOcrRequested.stream.name, retry_durable
                    )
                except NotFoundError:
                    pass
                await client.jetstream().purge_stream(
                    ReceiptOcrRequested.stream.name
                )
                await client.close()
                await publisher_app.stop()

            async with self.connection.uow() as independent:
                stored = await independent.execute(
                    select(ReceiptOcrOutboxTable).where(
                        col(ReceiptOcrOutboxTable.id) == first_claim.outbox_id
                    )
                )
                outbox = stored.scalar_one()
                self.assertEqual(outbox.status, "published")
                self.assertEqual(outbox.attempts, 2)
        finally:
            async with self.connection.uow() as unit:
                await unit.execute(text("SET FOREIGN_KEY_CHECKS=0"))
                async with unit.transaction():
                    await unit.execute(
                        text(
                            "DELETE FROM tbl_receipt_ocr_outboxes "
                            "WHERE receipt_id = :receipt_id"
                        ),
                        {"receipt_id": receipt.id},
                    )
                    await unit.execute(
                        text(
                            "DELETE FROM tbl_payment_receipts "
                            "WHERE id = :receipt_id"
                        ),
                        {"receipt_id": receipt.id},
                    )
                await unit.execute(text("SET FOREIGN_KEY_CHECKS=1"))

    async def test_upload_commits_receipt_and_unique_outbox_together(self):
        suffix = uuid4().hex
        settings = configured_settings()
        policy = ReceiptPolicy(
            enabled=True, max_per_topup=5, allowed_formats=["JPEG"]
        )
        preferences = SimpleNamespace(
            current=lambda **_: _receipt_preferences(policy)
        )
        content = _jpeg()

        async with self.connection.uow() as unit:
            async with unit.transaction():
                customer = await CustomerRepository(unit).create(
                    CustomerModel(display_name="outbox-test-" + suffix[:12])
                )
                topup = await TopupRepository(unit).create(
                    TopupModel(
                        customer_id=customer.id,
                        amount_rial=125_000,
                    )
                )

        try:
            async with self.connection.uow() as unit:
                with unit.activate():
                    command = PaymentReceiptCommand(
                        PaymentReceiptRepository(unit),
                        PaymentReceiptOutboxRepository(unit),
                        TopupRecordService(TopupRepository(unit)),
                        settings,
                        cast(IPreferencesService, preferences),
                        ReceiptImages(settings.receipts),
                    )
                    first = await command.upload(
                        topup.id, customer.id, content
                    )
                    duplicate = await command.upload(
                        topup.id, customer.id, content
                    )

            self.assertEqual(duplicate.id, first.id)
            async with self.connection.uow() as independent:
                outbox = await independent.execute(
                    select(ReceiptOcrOutboxTable).where(
                        col(ReceiptOcrOutboxTable.receipt_id) == first.id
                    )
                )
                self.assertEqual(outbox.scalar_one().status, "pending")
                receipt_count = await independent.execute(
                    select(func.count())
                    .select_from(ReceiptOcrOutboxTable)
                    .where(col(ReceiptOcrOutboxTable.receipt_id) == first.id)
                )
                self.assertEqual(receipt_count.scalar_one(), 1)
        finally:
            async with self.connection.uow() as unit:
                await unit.execute(text("SET FOREIGN_KEY_CHECKS=0"))
                async with unit.transaction():
                    await unit.execute(
                        text(
                            "DELETE FROM tbl_receipt_ocr_outboxes "
                            "WHERE receipt_id IN (SELECT id FROM "
                            "tbl_payment_receipts WHERE topup_id = :topup_id)"
                        ),
                        {"topup_id": topup.id},
                    )
                    await unit.execute(
                        text(
                            "DELETE FROM tbl_payment_receipts "
                            "WHERE topup_id = :topup_id"
                        ),
                        {"topup_id": topup.id},
                    )
                    await unit.execute(
                        text("DELETE FROM tbl_topups WHERE id = :topup_id"),
                        {"topup_id": topup.id},
                    )
                    await unit.execute(
                        text(
                            "DELETE FROM tbl_customers WHERE id = :customer_id"
                        ),
                        {"customer_id": customer.id},
                    )
                await unit.execute(text("SET FOREIGN_KEY_CHECKS=1"))

    async def test_ocr_event_stores_encrypted_result_once_on_redelivery(self):
        suffix = uuid4().hex
        settings = configured_settings()
        image = b"private-test-receipt-image"
        encrypted_payload = await asyncio.to_thread(
            encrypt,
            base64.b64encode(image).decode("ascii"),
            settings.configuration_encryption_key,
        )

        class ControlledOcr:
            def __init__(self) -> None:
                self.calls: list[bytes] = []

            async def recognize(self, content: bytes) -> ReceiptOcrResult:
                self.calls.append(content)
                return ReceiptOcrResult(
                    lines=(
                        ReceiptOcrLine(
                            text="مبلغ انتقال", confidence_milli=950
                        ),
                        ReceiptOcrLine(
                            text="۱۰۰۰۰۰ ریال", confidence_milli=930
                        ),
                        ReceiptOcrLine(
                            text="شماره پیگیری: 12345678",
                            confidence_milli=910,
                        ),
                    )
                )

        ocr = ControlledOcr()
        async with self.connection.uow() as unit:
            await unit.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            async with unit.transaction():
                receipt = await PaymentReceiptRepository(unit).create(
                    PaymentReceiptModel(
                        topup_id=2_000_000_000,
                        content_hash=suffix[:64],
                        media_type="image/jpeg",
                        size_bytes=len(image),
                        encrypted_payload=encrypted_payload,
                    )
                )
            await unit.execute(text("SET FOREIGN_KEY_CHECKS=1"))
        async with self.connection.uow() as independent:
            wallet_entries = await independent.execute(
                text("SELECT COUNT(*) FROM tbl_wallet_entries")
            )
            wallet_entry_count = wallet_entries.scalar_one()

        durable = "receipt-ocr-result-" + suffix[:12]
        broker = NatsBroker(NativeNatsBroker(str(NATS_TEST_URL)))
        registrar = JetRegistrar(broker)
        registrar.publisher(ReceiptOcrRequested)
        publisher_app = events_app(registrar=registrar)
        await publisher_app.start()
        client = await nats.connect(str(NATS_TEST_URL))
        try:
            jetstream = client.jetstream()
            await jetstream.purge_stream(ReceiptOcrRequested.stream.name)
            subscription = await client.jetstream().pull_subscribe(
                ReceiptOcrRequested.subject,
                durable=durable,
                stream=ReceiptOcrRequested.stream.name,
            )
            await ReceiptOcrRequested.publish(
                ReceiptOcrRequest(receipt_id=receipt.id)
            )
            first_messages = await subscription.fetch(1, timeout=5)
            first_message = next(iter(first_messages))
            await self._process_ocr_delivery(settings, ocr, first_message.data)
            await first_message.ack()

            await ReceiptOcrRequested.publish(
                ReceiptOcrRequest(receipt_id=receipt.id)
            )
            replayed_messages = await subscription.fetch(1, timeout=5)
            replayed_message = next(iter(replayed_messages))
            await self._process_ocr_delivery(
                settings, ocr, replayed_message.data
            )
            await replayed_message.ack()

            async with self.connection.uow() as independent:
                stored = await independent.execute(
                    select(PaymentReceiptTable).where(
                        col(PaymentReceiptTable.id) == receipt.id
                    )
                )
                result = stored.scalar_one()
                self.assertEqual(result.ocr_status, "complete")
                self.assertIsNotNone(result.encrypted_extraction)
                self.assertNotIn("12345678", result.encrypted_extraction or "")
                extraction = ReceiptExtractionFields.model_validate_json(
                    decrypt(
                        result.encrypted_extraction or "",
                        settings.configuration_encryption_key,
                    )
                )
                self.assertEqual(extraction.amount_rial, 100_000)
                self.assertEqual(extraction.bank_reference, "12345678")
                wallet_entries = await independent.execute(
                    text("SELECT COUNT(*) FROM tbl_wallet_entries")
                )
                self.assertEqual(
                    wallet_entries.scalar_one(), wallet_entry_count
                )
            self.assertEqual(ocr.calls, [image])
        finally:
            try:
                await client.jetstream().delete_consumer(
                    ReceiptOcrRequested.stream.name, durable
                )
            except NotFoundError:
                pass
            await client.jetstream().purge_stream(
                ReceiptOcrRequested.stream.name
            )
            await client.close()
            await publisher_app.stop()
            async with self.connection.uow() as unit:
                await unit.execute(text("SET FOREIGN_KEY_CHECKS=0"))
                async with unit.transaction():
                    await unit.execute(
                        text(
                            "DELETE FROM tbl_receipt_ocr_outboxes "
                            "WHERE receipt_id=:id"
                        ),
                        {"id": receipt.id},
                    )
                    await unit.execute(
                        text("DELETE FROM tbl_payment_receipts WHERE id=:id"),
                        {"id": receipt.id},
                    )
                await unit.execute(text("SET FOREIGN_KEY_CHECKS=1"))

    async def _claim(self):
        async with self.connection.uow() as unit:
            async with unit.transaction():
                claim = await PaymentReceiptOutboxRepository(unit).claim_next()
            return claim

    async def _process_ocr_delivery(
        self,
        settings: PapilioSettings,
        ocr: IReceiptOcrApi,
        payload: bytes,
    ) -> None:
        event = ReceiptOcrRequest.model_validate_json(payload)
        async with self.connection.uow() as unit:
            with unit.activate():
                consumer = ReceiptOcrConsumer(
                    PaymentReceiptOcrCommand(
                        PaymentReceiptRepository(unit), settings, ocr
                    )
                )
                await consumer.run(event)


async def _receipt_preferences(policy: ReceiptPolicy):
    return SimpleNamespace(values=SimpleNamespace(receipts=policy))


def _jpeg() -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 32), "white").save(output, format="JPEG")
    content = output.getvalue()
    return content
