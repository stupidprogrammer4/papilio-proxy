from __future__ import annotations

import asyncio
import base64
import json
import os
from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase, skipUnless
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.infra.db.access import MysqlAccessRepository
from bot.infra.db.admin_web import MysqlAdminWebRepository
from bot.infra.db.checkout import MysqlCheckoutRepository
from bot.infra.db.mysql import MysqlSubscriptionRepository
from bot.infra.db.payments import MysqlPaymentRepository
from bot.infra.db.user_access import MysqlUserAccessRepository
from bot.models import Plan, Protocol, TelegramUser
from bot.models.payments import PaymentInitiation, ProviderVerification
from bot.models.user_access import UnknownUserError, UserBlockedError
from bot.services.access import AccessService
from bot.services.subscriptions import SubscriptionService


@skipUnless(os.getenv("PAPILIO_TEST_DATABASE_URL"), "Requires explicit MySQL URL")
class UserAccessMysqlTests(IsolatedAsyncioTestCase):
    async def test_block_all_access_preserves_paid_orders_and_rolls_back(self) -> None:
        url = os.environ["PAPILIO_TEST_DATABASE_URL"]
        subscriptions = MysqlSubscriptionRepository(url)
        access = MysqlAccessRepository(url, Fernet.generate_key().decode())
        policies = MysqlUserAccessRepository(url)
        admin = MysqlAdminWebRepository(url)
        checkout = MysqlCheckoutRepository(url)
        payments = MysqlPaymentRepository(url)
        owner = -(uuid4().int % 2**40 + 1)
        other = owner - 1
        code = "blocktest_" + uuid4().hex[:20]
        adapters = (
            (subscriptions, "_session_factory"), (access, "_session_factory"),
            (policies, "_sessions"), (admin, "_sessions"),
            (checkout, "_session_factory"), (payments, "_session_factory"),
        )
        try:
            await subscriptions.initialize()
            async with subscriptions._engine.connect() as connection:
                transaction = await connection.begin()
                factory = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint",
                )
                originals = [(obj, name, getattr(obj, name)) for obj, name in adapters]
                for obj, name in adapters:
                    setattr(obj, name, factory)
                try:
                    await subscriptions.save(Plan(code, "Block test", 1, 1, 100_000))
                    service = SubscriptionService(subscriptions, subscriptions)
                    access_service = AccessService(access)
                    await service.register_user(TelegramUser(owner, code, None))
                    await service.register_user(TelegramUser(other, code + "-other", None))

                    async def paid_order(telegram_id: int) -> str:
                        order = await service.create_order(telegram_id, code, Protocol.BOTH)
                        attempt = PaymentInitiation(
                            "test-tx-" + uuid4().hex, "test-auth-" + uuid4().hex,
                            100_000, "https://kpay.website/pay/test",
                        )
                        await payments.attach_checkout(order.id, attempt)
                        await payments.settle_verified(ProviderVerification(
                            attempt.authority, "paid", attempt.transaction_id,
                            attempt.amount_rial, datetime.now(UTC).isoformat(),
                        ))
                        return order.id

                    async def activate(identifier: str):
                        vmess = "vmess://" + base64.b64encode(json.dumps({
                            "id": identifier, "add": "node.example",
                        }).encode()).decode()
                        return await access_service.record_provisioned(
                            identifier, f"vless://{identifier}@node.example:443", vmess,
                            datetime.now(UTC).replace(microsecond=0),
                        )

                    identifier = await paid_order(owner)
                    neighbor_id = await paid_order(other)
                    pending_id = await paid_order(owner)
                    first = await activate(identifier)
                    neighbor = await activate(neighbor_id)
                    rows = await admin.list_users(code)
                    self.assertFalse(next(row for row in rows if row.telegram_id == owner).is_blocked)
                    saved = await policies.set_blocked(owner, True, "abuse", "test-admin")
                    self.assertEqual(set(saved), {identifier, pending_id})
                    self.assertIsNone(await access_service.get_by_token(first.token))
                    self.assertIsNone(await access_service.get_for_user(owner, identifier))
                    self.assertIsNone(await checkout.get_order(owner, identifier))
                    self.assertNotIn(identifier, {
                        row.access.subscription_id for row in await access.list_active_node_access()
                    })
                    self.assertNotIn(pending_id, {row.subscription_id for row in await access.list_pending_paid()})
                    self.assertNotIn(identifier, {row.subscription_id for row in await access.claim_deliveries()})
                    with self.assertRaises(UserBlockedError):
                        await activate(pending_id)
                    with self.assertRaises(UserBlockedError):
                        await service.create_order(owner, code, Protocol.BOTH)
                    with self.assertRaises(UserBlockedError):
                        await checkout.claim(pending_id)
                    with self.assertRaises(UnknownUserError):
                        await policies.set_blocked(owner - 99, True, "", "test-admin")
                    self.assertIsNotNone(await access_service.get_by_token(neighbor.token))
                    self.assertIn(neighbor_id, {
                        row.access.subscription_id for row in await access.list_active_node_access()
                    })
                    user = next(row for row in await admin.list_users(code) if row.telegram_id == owner)
                    self.assertTrue(user.is_blocked)
                    self.assertEqual(user.block_reason, "abuse")
                    self.assertTrue(next(row for row in await admin.list_orders()
                                         if row.id == identifier).is_blocked)
                    await policies.set_blocked(owner, False, "reviewed", "test-admin")
                    restored = await access_service.get_by_token(first.token)
                    assert restored is not None
                    self.assertEqual(restored.token, first.token)
                    self.assertEqual(restored.expires_at, first.expires_at)
                    self.assertEqual(restored.traffic_limit_bytes, first.traffic_limit_bytes)
                    self.assertEqual(restored.traffic_used_bytes, first.traffic_used_bytes)
                    self.assertIn(pending_id, {row.subscription_id for row in await access.list_pending_paid()})
                    self.assertIn(identifier, {row.subscription_id for row in await access.claim_deliveries()})
                    self.assertFalse(next(row for row in await admin.list_users(code)
                                          if row.telegram_id == owner).is_blocked)
                finally:
                    await transaction.rollback()
                    for obj, name, original in originals:
                        setattr(obj, name, original)
            self.assertEqual(await subscriptions.list_for_user(owner), [])
            self.assertIsNone(await subscriptions.get(code))
        finally:
            await asyncio.gather(*(obj.close() for obj, _ in adapters))
