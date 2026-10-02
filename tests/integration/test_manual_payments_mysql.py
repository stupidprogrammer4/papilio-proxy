from __future__ import annotations

import os
from unittest import IsolatedAsyncioTestCase, skipUnless
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from papilio_proxy.modules.sales.payments.app.services import PaymentService
from papilio_proxy.modules.sales.payments.domain.entities import PaymentError, ReceiptStatus
from papilio_proxy.modules.sales.payments.infra.images import sanitize_receipt
from papilio_proxy.modules.sales.payments.infra.repository import MysqlPaymentRepository
from papilio_proxy.modules.sales.payments.infra.tables import PaymentReceiptModel
from papilio_proxy.modules.sales.subscriptions.domain.entities import (
    Plan,
    SubscriptionStatus,
    TelegramUser,
)
from papilio_proxy.modules.sales.subscriptions.infra.repository import MysqlSubscriptionRepository
from tests.fixtures import receipt_image


@skipUnless(os.getenv("PAPILIO_TEST_DATABASE_URL"), "Requires explicit MySQL URL")
class ManualPaymentsMysqlTests(IsolatedAsyncioTestCase):
    async def test_destination_receipts_review_replay_and_transaction_uniqueness(self) -> None:
        url = os.environ["PAPILIO_TEST_DATABASE_URL"]
        catalog = MysqlSubscriptionRepository(url)
        payments = MysqlPaymentRepository(url, Fernet.generate_key().decode())
        service = PaymentService(payments)
        owner = -(uuid4().int % 2**40 + 1)
        code = "manual_" + uuid4().hex[:20]
        try:
            await catalog.initialize()
            async with catalog._engine.connect() as connection:
                transaction = await connection.begin()
                original_catalog, original_payments = (
                    catalog._session_factory,
                    payments._session_factory,
                )
                factory = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
                )
                catalog._session_factory = payments._session_factory = factory
                try:
                    await catalog.save(Plan(code, "Test plan", 2, 3, 100_000))
                    for customer in (owner, owner - 1):
                        await catalog.upsert_user(TelegramUser(customer, code, None))
                    method = await service.save_method(
                        method_id=None,
                        title="Card",
                        card_number="1111222233334444",
                        bank_name="First bank",
                        account_holder="First owner",
                        enabled=True,
                    )
                    order = await service.begin(owner, code, method.id)
                    repeat = await service.begin(owner, code, method.id)
                    self.assertEqual(order.order_id, repeat.order_id)
                    await service.save_method(
                        method_id=method.id,
                        title="Changed",
                        card_number="4444333322221111",
                        bank_name="Second bank",
                        account_holder="Second owner",
                        enabled=True,
                    )
                    self.assertEqual(await service.instructions(owner, order.order_id), order)
                    neighbor = await service.begin(owner - 1, code, method.id)
                    self.assertEqual(neighbor.bank_name, "Second bank")
                    with self.assertRaises(PaymentError):
                        await service.instructions(owner - 1, order.order_id)
                    image = receipt_image(uuid4().hex)
                    with self.assertRaises(PaymentError):
                        await service.submit_receipt(owner - 1, order.order_id, image)
                    first_receipt = await service.submit_receipt(owner, order.order_id, image)
                    self.assertEqual(
                        await service.submit_receipt(owner, order.order_id, image), first_receipt
                    )
                    self.assertEqual(
                        await service.status(owner, order.order_id), ReceiptStatus.PENDING
                    )
                    self.assertEqual(
                        (await catalog.list_for_user(owner))[0].status,
                        SubscriptionStatus.PENDING_PAYMENT,
                    )
                    self.assertEqual(
                        await service.receipt_image(first_receipt), await sanitize_receipt(image)
                    )
                    stored = await connection.scalar(
                        select(PaymentReceiptModel.image_ciphertext).where(
                            PaymentReceiptModel.id == first_receipt
                        )
                    )
                    self.assertNotEqual(stored, image)
                    with self.assertRaises(PaymentError):
                        await service.submit_receipt(owner - 1, neighbor.order_id, image)
                    neighbor_receipt = await service.submit_receipt(
                        owner - 1, neighbor.order_id, receipt_image(uuid4().hex)
                    )
                    await service.review(
                        first_receipt, approved=False, actor="test", reason="Incorrect amount"
                    )
                    with self.assertRaises(PaymentError):
                        await service.review(
                            first_receipt, approved=True, actor="test", bank_reference=uuid4().hex
                        )
                    second_receipt = await service.submit_receipt(
                        owner, order.order_id, receipt_image(uuid4().hex)
                    )
                    bank_reference = uuid4().hex
                    await service.review(
                        second_receipt, approved=True, actor="test", bank_reference=bank_reference
                    )
                    await service.review(
                        second_receipt, approved=True, actor="test", bank_reference=bank_reference
                    )
                    with self.assertRaises(PaymentError):
                        await service.review(
                            neighbor_receipt,
                            approved=True,
                            actor="test",
                            bank_reference=bank_reference,
                        )
                    self.assertEqual(
                        (await catalog.list_for_user(owner))[0].status,
                        SubscriptionStatus.PAID_AWAITING_PROVISIONING,
                    )
                    self.assertEqual(
                        (await catalog.list_for_user(owner - 1))[0].status,
                        SubscriptionStatus.PENDING_PAYMENT,
                    )
                    row = next(row for row in await service.receipts() if row.id == second_receipt)
                    self.assertEqual(row.bank_reference, bank_reference.upper())
                    self.assertEqual(row.card_number, "1111222233334444")
                    self.assertEqual(row.reviewed_by, "test")
                    notices = await payments.claim_notifications()
                    self.assertIn(second_receipt, {notice.receipt_id for notice in notices})
                    self.assertNotIn(
                        second_receipt,
                        {notice.receipt_id for notice in await payments.claim_notifications()},
                    )
                    await payments.finish_notification(second_receipt, sent=False)
                    self.assertIn(
                        second_receipt,
                        {notice.receipt_id for notice in await payments.claim_notifications()},
                    )
                    await payments.finish_notification(second_receipt, sent=True)
                    self.assertNotIn(
                        second_receipt,
                        {notice.receipt_id for notice in await payments.claim_notifications()},
                    )
                finally:
                    await transaction.rollback()
                    catalog._session_factory, payments._session_factory = (
                        original_catalog,
                        original_payments,
                    )
            self.assertIsNone(await catalog.get(code))
            self.assertEqual(await catalog.list_for_user(owner), [])
        finally:
            await catalog.close()
            await payments.close()
