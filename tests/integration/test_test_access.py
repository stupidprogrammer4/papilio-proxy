from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase, skipUnless
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.infra.db.access import MysqlAccessRepository
from bot.infra.db.mysql import MysqlSubscriptionRepository
from bot.infra.db.test_access import MysqlTestAccessRepository
from bot.models.subscriptions import SubscriptionStatus, TelegramUser
from bot.services.access import AccessService
from bot.services.test_access import TestAccessService


@skipUnless(os.getenv("PAPILIO_TEST_DATABASE_URL"), "Requires explicit MySQL URL")
class TestGrantRepositoryTests(IsolatedAsyncioTestCase):
    async def test_private_pilot_is_zero_revenue_and_provisionable(self) -> None:
        url = os.environ["PAPILIO_TEST_DATABASE_URL"]
        trial = MysqlTestAccessRepository(url)
        users = MysqlSubscriptionRepository(url)
        access = MysqlAccessRepository(url, Fernet.generate_key().decode())
        owner = -(uuid4().int % 2**40 + 1)
        try:
            await trial.initialize()
            async with trial._engine.connect() as connection:
                transaction = await connection.begin()
                factory = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
                )
                original_trial = trial._sessions
                original_users = users._session_factory
                original_access = access._session_factory
                trial._sessions = factory
                users._session_factory = factory
                access._session_factory = factory
                try:
                    await users.upsert_user(TelegramUser(owner, "Pilot admin", None))
                    service = TestAccessService(trial, frozenset({owner}))
                    order_id = await service.grant(owner, 128, 1)
                    with self.assertRaises(ValueError):
                        await service.grant(owner, 128, 1)
                    rows = await users.list_for_user(owner)
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0].price_rial, 0)
                    self.assertEqual(rows[0].status, SubscriptionStatus.TEST_AWAITING_PROVISIONING)
                    pending = await access.list_pending_paid()
                    self.assertIn(order_id, {item.subscription_id for item in pending})
                    identifier = "123e4567-e89b-42d3-a456-426614174000"
                    vless = f"vless://{identifier}@node.example:443?security=reality#Pilot"
                    vmess = "vmess://" + base64.b64encode(
                        json.dumps({"id": identifier, "add": "node.example"}).encode()
                    ).decode()
                    issued = await AccessService(access).record_provisioned(
                        order_id, vless, vmess, datetime.now(UTC)
                    )
                    self.assertEqual(issued.traffic_limit_bytes, 128 * 1024**2)
                    self.assertEqual(issued.status, SubscriptionStatus.ACTIVE)
                    self.assertEqual(
                        (await users.list_for_user(owner))[0].status, SubscriptionStatus.ACTIVE
                    )
                finally:
                    await transaction.rollback()
                    trial._sessions = original_trial
                    users._session_factory = original_users
                    access._session_factory = original_access
        finally:
            await trial.close()
            await users.close()
            await access.close()
