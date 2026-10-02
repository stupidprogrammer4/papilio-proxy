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

from papilio_proxy.modules.accounts.admin.infra.repository import MysqlAdminWebRepository
from papilio_proxy.modules.accounts.users.domain.entities import UnknownUserError, UserBlockedError
from papilio_proxy.modules.accounts.users.infra.repository import MysqlUserAccessRepository
from papilio_proxy.modules.network.subscriptions.app.services import AccessService
from papilio_proxy.modules.network.subscriptions.infra.repository import MysqlAccessRepository
from papilio_proxy.modules.sales.payments.app.services import PaymentService
from papilio_proxy.modules.sales.payments.infra.repository import MysqlPaymentRepository
from papilio_proxy.modules.sales.subscriptions.app.services import SubscriptionService
from papilio_proxy.modules.sales.subscriptions.domain.entities import Plan, Protocol, TelegramUser
from papilio_proxy.modules.sales.subscriptions.infra.repository import MysqlSubscriptionRepository
from tests.fixtures import receipt_image


@skipUnless(os.getenv("PAPILIO_TEST_DATABASE_URL"), "Requires explicit MySQL URL")
class UserAccessMysqlTests(IsolatedAsyncioTestCase):
    async def test_block_all_access_preserves_paid_orders_and_rolls_back(self) -> None:
        url = os.environ["PAPILIO_TEST_DATABASE_URL"]
        subscriptions = MysqlSubscriptionRepository(url)
        access = MysqlAccessRepository(url, Fernet.generate_key().decode())
        policies = MysqlUserAccessRepository(url)
        admin = MysqlAdminWebRepository(url)
        payments = MysqlPaymentRepository(url, Fernet.generate_key().decode())
        owner = -(uuid4().int % 2**40 + 1)
        other = owner - 1
        code = "blocktest_" + uuid4().hex[:20]
        adapters = (
            (subscriptions, "_session_factory"),
            (access, "_session_factory"),
            (policies, "_sessions"),
            (admin, "_sessions"),
            (payments, "_session_factory"),
        )
        try:
            await subscriptions.initialize()
            async with subscriptions._engine.connect() as connection:
                transaction = await connection.begin()
                factory = async_sessionmaker(
                    connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
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

                    payment_service = PaymentService(payments)
                    method = await payment_service.save_method(
                        method_id=None,
                        title="Test",
                        card_number="1111222233334444",
                        bank_name="Test bank",
                        account_holder="Test holder",
                        enabled=True,
                    )

                    async def paid_order(telegram_id: int) -> str:
                        instructions = await payment_service.begin(telegram_id, code, method.id)
                        receipt = await payment_service.submit_receipt(
                            telegram_id, instructions.order_id, receipt_image(uuid4().hex)
                        )
                        await payment_service.review(
                            receipt, approved=True, actor="test", bank_reference=uuid4().hex
                        )
                        return instructions.order_id

                    async def activate(identifier: str):
                        vmess = (
                            "vmess://"
                            + base64.b64encode(
                                json.dumps(
                                    {
                                        "id": identifier,
                                        "add": "node.example",
                                    }
                                ).encode()
                            ).decode()
                        )
                        return await access_service.record_provisioned(
                            identifier,
                            f"vless://{identifier}@node.example:443",
                            vmess,
                            datetime.now(UTC).replace(microsecond=0),
                        )

                    identifier = await paid_order(owner)
                    neighbor_id = await paid_order(other)
                    pending_id = await paid_order(owner)
                    first = await activate(identifier)
                    neighbor = await activate(neighbor_id)
                    rows = await admin.list_users(code)
                    self.assertFalse(
                        next(row for row in rows if row.telegram_id == owner).is_blocked
                    )
                    saved = await policies.set_blocked(owner, True, "abuse", "test-admin")
                    self.assertEqual(set(saved), {identifier, pending_id})
                    self.assertIsNone(await access_service.get_by_token(first.token))
                    self.assertIsNone(await access_service.get_for_user(owner, identifier))
                    with self.assertRaises(UserBlockedError):
                        await payment_service.instructions(owner, identifier)
                    self.assertNotIn(
                        identifier,
                        {
                            row.access.subscription_id
                            for row in await access.list_active_node_access()
                        },
                    )
                    self.assertNotIn(
                        pending_id,
                        {row.subscription_id for row in await access.list_pending_paid()},
                    )
                    self.assertNotIn(
                        identifier, {row.subscription_id for row in await access.claim_deliveries()}
                    )
                    with self.assertRaises(UserBlockedError):
                        await activate(pending_id)
                    with self.assertRaises(UserBlockedError):
                        await service.create_order(owner, code, Protocol.BOTH)
                    with self.assertRaises(UserBlockedError):
                        await payment_service.begin(owner, code, method.id)
                    with self.assertRaises(UnknownUserError):
                        await policies.set_blocked(owner - 99, True, "", "test-admin")
                    self.assertIsNotNone(await access_service.get_by_token(neighbor.token))
                    self.assertIn(
                        neighbor_id,
                        {
                            row.access.subscription_id
                            for row in await access.list_active_node_access()
                        },
                    )
                    user = next(
                        row for row in await admin.list_users(code) if row.telegram_id == owner
                    )
                    self.assertTrue(user.is_blocked)
                    self.assertEqual(user.block_reason, "abuse")
                    self.assertTrue(
                        next(
                            row for row in await admin.list_orders() if row.id == identifier
                        ).is_blocked
                    )
                    await policies.set_blocked(owner, False, "reviewed", "test-admin")
                    restored = await access_service.get_by_token(first.token)
                    assert restored is not None
                    self.assertEqual(restored.token, first.token)
                    self.assertEqual(restored.expires_at, first.expires_at)
                    self.assertEqual(restored.traffic_limit_bytes, first.traffic_limit_bytes)
                    self.assertEqual(restored.traffic_used_bytes, first.traffic_used_bytes)
                    self.assertIn(
                        pending_id,
                        {row.subscription_id for row in await access.list_pending_paid()},
                    )
                    self.assertIn(
                        identifier, {row.subscription_id for row in await access.claim_deliveries()}
                    )
                    self.assertFalse(
                        next(
                            row for row in await admin.list_users(code) if row.telegram_id == owner
                        ).is_blocked
                    )
                finally:
                    await transaction.rollback()
                    for obj, name, original in originals:
                        setattr(obj, name, original)
            self.assertEqual(await subscriptions.list_for_user(owner), [])
            self.assertIsNone(await subscriptions.get(code))
        finally:
            await asyncio.gather(*(obj.close() for obj, _ in adapters))
