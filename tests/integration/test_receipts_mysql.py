from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase, skipUnless
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.infra.db.mysql import MysqlSubscriptionRepository
from bot.infra.db.payments import MysqlPaymentRepository
from bot.infra.db.receipts import MysqlReceiptRepository
from bot.models import Plan, Protocol, TelegramUser
from bot.models.payments import PaymentInitiation, ProviderVerification
from bot.models.receipts import ReceiptUnavailable
from bot.services.subscriptions import SubscriptionService


@skipUnless(os.getenv("PAPILIO_TEST_DATABASE_URL"), "Requires explicit MySQL URL")
class ReceiptMysqlTests(IsolatedAsyncioTestCase):
    async def test_duplicate_image_and_paid_retries_roll_back(self) -> None:
        url = os.environ["PAPILIO_TEST_DATABASE_URL"]
        subscriptions = MysqlSubscriptionRepository(url)
        payments = MysqlPaymentRepository(url)
        receipts = MysqlReceiptRepository(url)
        repositories = (subscriptions, payments, receipts)
        originals = [repo._session_factory for repo in repositories]
        suffix = uuid4().hex[:18]
        user = -(uuid4().int % 2**40 + 1)
        try:
            await subscriptions.initialize()
            await receipts.initialize()
            async with subscriptions._engine.connect() as connection:
                transaction = await connection.begin()
                factory = async_sessionmaker(connection, expire_on_commit=False,
                                             join_transaction_mode="create_savepoint")
                for repo in repositories:
                    repo._session_factory = factory
                try:
                    await receipts.set_enabled(True)
                    self.assertTrue(await receipts.enabled())
                    await subscriptions.save(Plan(suffix, "Receipt test", 1, 1, 50_000))
                    service = SubscriptionService(subscriptions, subscriptions)
                    await service.register_user(TelegramUser(user, suffix, None))
                    orders = [await service.create_order(user, suffix, Protocol.BOTH) for _ in range(2)]
                    attempts = []
                    for order in orders:
                        attempt = PaymentInitiation(str(uuid4()), uuid4().hex, 50_000,
                                                    "https://kpay.website/pay/test")
                        await payments.attach_checkout(order.id, attempt)
                        attempts.append(attempt)
                    bound = await receipts.bound_order(attempts[0].authority)
                    self.assertIsNotNone(bound)
                    self.assertFalse(await receipts.reserve(orders[0].id, suffix.ljust(64, "0")))
                    await receipts.mark_uploaded(orders[0].id)
                    self.assertTrue(await receipts.reserve(orders[0].id, suffix.ljust(64, "0")))
                    with self.assertRaises(ReceiptUnavailable):
                        await receipts.reserve(orders[1].id, suffix.ljust(64, "0"))
                    self.assertEqual(await receipts.pending_uploads(), [attempts[0].authority])
                    result = ProviderVerification(attempts[0].authority, "paid", attempts[0].transaction_id,
                                                  50_000, datetime.now(UTC).isoformat())
                    self.assertTrue(await payments.settle_verified(result))
                    self.assertTrue(await payments.settle_verified(result))
                    self.assertEqual(await receipts.pending_uploads(), [])
                    self.assertIsNone(await receipts.bound_order(attempts[0].authority))
                finally:
                    for repo, original in zip(repositories, originals, strict=True):
                        repo._session_factory = original
                    await transaction.rollback()
        finally:
            for repo in repositories:
                await repo.close()
