import asyncio
import importlib.util
import os
from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

import httpx
import yaml
from alembic import command
from alembic.config import Config
from papilio.api.application import create_app
from papilio.errors.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.security.crypto import decrypt, encrypt
from sqlalchemy import select, text
from sqlmodel import col
from starlette.middleware import Middleware

from src.config.middleware import SecurityHeadersMiddleware
from src.config.providers import infrastructure_providers
from src.config.settings import PapilioSettings
from src.modules.accounts.customers.domain.models import CustomerModel
from src.modules.accounts.customers.infra.mysql import CustomerRepository
from src.modules.accounts.staff.app.passwords import Passwords
from src.modules.accounts.staff.domain.models import StaffModel
from src.modules.accounts.staff.domain.results import Principal
from src.modules.accounts.staff.infra.mysql import StaffRepository
from src.modules.billing.receipts.app.annotations import (
    ReceiptAnnotationCommand,
)
from src.modules.billing.receipts.domain.annotations import (
    ReceiptAnnotationWrite,
    ReceiptCorrectionFields,
)
from src.modules.billing.receipts.domain.models import PaymentReceiptModel
from src.modules.billing.receipts.infra.mysql import (
    PaymentReceiptAnnotationRepository,
    PaymentReceiptRepository,
)
from src.modules.billing.receipts.infra.tables import PaymentReceiptTable
from src.modules.billing.wallet.domain.models import TopupModel
from src.modules.billing.wallet.infra.mysql import TopupRepository

TEST_DATABASE_URL = os.getenv("PAPILIO_TEST_DATABASE_URL")


def configured_settings() -> PapilioSettings:
    with open("config.yml.sample", encoding="utf-8") as source:
        raw = yaml.safe_load(source)
    raw["db"]["dsn"] = TEST_DATABASE_URL
    raw["db"]["test_dsn"] = TEST_DATABASE_URL
    raw["rate_limit"]["enabled"] = False
    return PapilioSettings.model_validate(raw)


@skipUnless(TEST_DATABASE_URL, "Requires an isolated MySQL test database")
class ReceiptAnnotationIntegrationTest(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        migration = Config("alembic.ini")
        migration.set_main_option("sqlalchemy.url", str(TEST_DATABASE_URL))
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(command.upgrade, migration, "head")
        settings = configured_settings()
        assert settings.db is not None
        self.settings = settings
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

    async def test_annotations_are_immutable_audited_and_revision_guarded(
        self,
    ):
        suffix = uuid4().hex[:12]
        async with self.connection.uow() as unit:
            async with unit.transaction():
                customer = await CustomerRepository(unit).create(
                    CustomerModel(display_name="receipt-annotation-" + suffix)
                )
                topup = await TopupRepository(unit).create(
                    TopupModel(customer_id=customer.id, amount_rial=500_000)
                )
                other_topup = await TopupRepository(unit).create(
                    TopupModel(customer_id=customer.id, amount_rial=600_000)
                )
                staff = await StaffRepository(unit).create(
                    StaffModel(
                        username="receipt-annotation-" + suffix,
                        password_hash="test-only",
                    )
                )
                original_extraction = await asyncio.to_thread(
                    encrypt,
                    '{"amount_rial":125000}',
                    self.settings.configuration_encryption_key,
                )
                receipt = await PaymentReceiptRepository(unit).create(
                    PaymentReceiptModel(
                        topup_id=topup.id,
                        content_hash=suffix * 5 + suffix[:4],
                        media_type="image/jpeg",
                        size_bytes=12,
                        encrypted_payload="test-only-image-ciphertext",
                        encrypted_extraction=original_extraction,
                        ocr_status="complete",
                    )
                )

        try:
            principal = Principal(
                staff_id=staff.id,
                username=staff.username,
                scopes=frozenset({"payments:read", "payments:update"}),
                csrf_token="test-only",
                expires_at=datetime.now(UTC),
            )
            async with self.connection.uow() as unit:
                with unit.activate():
                    command = ReceiptAnnotationCommand(
                        PaymentReceiptRepository(unit),
                        PaymentReceiptAnnotationRepository(unit),
                        self.settings,
                    )
                    no_scope = Principal(
                        staff_id=staff.id,
                        username=staff.username,
                        scopes=frozenset(),
                        csrf_token="test-only",
                        expires_at=datetime.now(UTC),
                    )
                    with self.assertRaises(ForbiddenException):
                        await command.append(
                            topup.id,
                            receipt.id,
                            no_scope,
                            ReceiptAnnotationWrite(
                                expected_revision=0,
                                fields=ReceiptCorrectionFields(amount_rial=1),
                                reason="A denied write leaves no revision.",
                            ),
                        )
                    first = await command.append(
                        topup.id,
                        receipt.id,
                        principal,
                        ReceiptAnnotationWrite(
                            expected_revision=0,
                            fields=ReceiptCorrectionFields(
                                amount_rial=250_000,
                                currency="rial",
                                bank_reference="bank-ref-" + suffix,
                            ),
                            reason=(
                                "Operator matched the displayed transfer "
                                "amount."
                            ),
                        ),
                    )
                    second = await command.append(
                        topup.id,
                        receipt.id,
                        principal,
                        ReceiptAnnotationWrite(
                            expected_revision=1,
                            fields=ReceiptCorrectionFields(
                                amount_rial=300_000
                            ),
                            reason=(
                                "Corrected after checking the bank reference."
                            ),
                        ),
                    )
                    with self.assertRaises(ConflictException) as stale:
                        await command.append(
                            topup.id,
                            receipt.id,
                            principal,
                            ReceiptAnnotationWrite(
                                expected_revision=1,
                                fields=ReceiptCorrectionFields(amount_rial=1),
                                reason=(
                                    "Stale revision must not overwrite "
                                    "history."
                                ),
                            ),
                        )
                    self.assertEqual(
                        getattr(stale.exception, "message_code", None),
                        "receipt_annotation_revision_conflict",
                    )
                    with self.assertRaises(ForbiddenException):
                        await command.history(
                            topup.id, receipt.id, no_scope, 1, 20
                        )
                    with self.assertRaises(NotFoundException) as wrong_parent:
                        await command.history(
                            other_topup.id, receipt.id, principal, 1, 20
                        )
                    self.assertEqual(
                        getattr(wrong_parent.exception, "message_code", None),
                        "payment_receipt_not_found",
                    )
                    history = await command.history(
                        topup.id, receipt.id, principal, 1, 20
                    )
                    self.assertEqual(history.total_items, 2)
                    self.assertEqual(
                        [entry.revision for entry in history.items], [2, 1]
                    )
                    self.assertEqual(first.revision, 1)
                    self.assertEqual(second.fields.amount_rial, 300_000)

            async with self.connection.uow() as independent:
                result = await independent.execute(
                    select(PaymentReceiptTable).where(
                        col(PaymentReceiptTable.id) == receipt.id
                    )
                )
                persisted = result.scalar_one()
                self.assertEqual(persisted.annotation_revision, 2)
                self.assertEqual(
                    persisted.encrypted_extraction, original_extraction
                )
                encrypted_extraction = persisted.encrypted_extraction
                assert encrypted_extraction is not None
                self.assertEqual(
                    await asyncio.to_thread(
                        decrypt,
                        encrypted_extraction,
                        self.settings.configuration_encryption_key,
                    ),
                    '{"amount_rial":125000}',
                )
                self.assertEqual(persisted.ocr_status, "complete")
        finally:
            async with self.connection.uow() as unit:
                await unit.execute(text("SET FOREIGN_KEY_CHECKS=0"))
                async with unit.transaction():
                    await unit.execute(
                        text(
                            "DELETE FROM tbl_payment_receipt_annotations "
                            "WHERE receipt_id = :receipt_id"
                        ),
                        {"receipt_id": receipt.id},
                    )
                    await unit.execute(
                        text("DELETE FROM tbl_payment_receipts WHERE id=:id"),
                        {"id": receipt.id},
                    )
                    await unit.execute(
                        text("DELETE FROM tbl_topups WHERE id IN (:a, :b)"),
                        {"a": topup.id, "b": other_topup.id},
                    )
                    await unit.execute(
                        text("DELETE FROM tbl_staff WHERE id=:id"),
                        {"id": staff.id},
                    )
                    await unit.execute(
                        text("DELETE FROM tbl_customers WHERE id=:id"),
                        {"id": customer.id},
                    )
                await unit.execute(text("SET FOREIGN_KEY_CHECKS=1"))

    @skipUnless(
        importlib.util.find_spec("nats") is not None,
        "Requires the project's NATS runtime dependency for app bootstrap",
    )
    async def test_admin_api_enforces_annotation_scope_and_revision(self):
        suffix = uuid4().hex[:12]
        password = "annotation-writer-password"
        reader_password = "annotation-reader-password"
        async with self.connection.uow() as unit:
            async with unit.transaction():
                customer = await CustomerRepository(unit).create(
                    CustomerModel(display_name="receipt-api-" + suffix)
                )
                topup = await TopupRepository(unit).create(
                    TopupModel(customer_id=customer.id, amount_rial=500_000)
                )
                password_hasher = Passwords(self.settings)
                writer = await StaffRepository(unit).create(
                    StaffModel(
                        username="receipt-writer-" + suffix,
                        password_hash=await password_hasher.hash(password),
                    )
                )
                await StaffRepository(unit).add_grant(
                    writer.id, "payments:update"
                )
                reader = await StaffRepository(unit).create(
                    StaffModel(
                        username="receipt-reader-" + suffix,
                        password_hash=await password_hasher.hash(
                            reader_password
                        ),
                    )
                )
                await StaffRepository(unit).add_grant(
                    reader.id, "payments:read"
                )
                receipt = await PaymentReceiptRepository(unit).create(
                    PaymentReceiptModel(
                        topup_id=topup.id,
                        content_hash=suffix * 5 + suffix[:4],
                        media_type="image/jpeg",
                        size_bytes=12,
                        encrypted_payload="test-only-image-ciphertext",
                    )
                )

        try:
            app = create_app(
                self.settings,
                providers=infrastructure_providers(self.settings),
                middleware=[Middleware(SecurityHeadersMiddleware)],
                docs_url=None,
            )
            origin = self.settings.public.admin_origin
            path = (
                f"/v1/admin/payments/topups/{topup.id}/receipts/"
                f"{receipt.id}/annotations"
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=origin
            ) as client:
                writer_login = await client.post(
                    "/v1/admin/auth/login",
                    headers={"Origin": origin},
                    json={"username": writer.username, "password": password},
                )
                self.assertEqual(writer_login.status_code, 200)
                writer_headers = {
                    "Origin": origin,
                    "X-CSRF-Token": writer_login.json()["csrf_token"],
                }
                data = {
                    "expected_revision": 0,
                    "fields": {"amount_rial": 400_000},
                    "reason": "Verified through the staff review API.",
                }
                saved = await client.put(
                    path, headers=writer_headers, json=data
                )
                self.assertEqual(saved.status_code, 200, saved.text)
                self.assertEqual(saved.json()["data"]["revision"], 1)
                stale = await client.put(
                    path, headers=writer_headers, json=data
                )
                self.assertEqual(stale.status_code, 409)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=origin
            ) as reader_client:
                reader_login = await reader_client.post(
                    "/v1/admin/auth/login",
                    headers={"Origin": origin},
                    json={
                        "username": reader.username,
                        "password": reader_password,
                    },
                )
                self.assertEqual(reader_login.status_code, 200)
                reader_headers = {
                    "Origin": origin,
                    "X-CSRF-Token": reader_login.json()["csrf_token"],
                }
                history = await reader_client.get(path)
                self.assertEqual(history.status_code, 200)
                denied = await reader_client.put(
                    path,
                    headers=reader_headers,
                    json={
                        "expected_revision": 1,
                        "fields": {"amount_rial": 1},
                        "reason": (
                            "Read-only staff cannot edit receipt claims."
                        ),
                    },
                )
                self.assertEqual(denied.status_code, 403)
        finally:
            async with self.connection.uow() as unit:
                await unit.execute(text("SET FOREIGN_KEY_CHECKS=0"))
                async with unit.transaction():
                    await unit.execute(
                        text(
                            "DELETE FROM tbl_payment_receipt_annotations "
                            "WHERE receipt_id=:receipt_id"
                        ),
                        {"receipt_id": receipt.id},
                    )
                    await unit.execute(
                        text("DELETE FROM tbl_payment_receipts WHERE id=:id"),
                        {"id": receipt.id},
                    )
                    await unit.execute(
                        text("DELETE FROM tbl_topups WHERE id=:id"),
                        {"id": topup.id},
                    )
                    await unit.execute(
                        text("DELETE FROM tbl_staff WHERE id IN (:a, :b)"),
                        {"a": writer.id, "b": reader.id},
                    )
                    await unit.execute(
                        text("DELETE FROM tbl_customers WHERE id=:id"),
                        {"id": customer.id},
                    )
                await unit.execute(text("SET FOREIGN_KEY_CHECKS=1"))
