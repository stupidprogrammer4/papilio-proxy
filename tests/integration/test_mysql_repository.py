from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase, skipUnless
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.infra.db.access import MysqlAccessRepository
from bot.infra.db.models import SubscriptionAccessModel
from bot.infra.db.mysql import MysqlSubscriptionRepository
from bot.infra.db.payments import MysqlPaymentRepository
from bot.models import Protocol, TelegramUser
from bot.models.payments import PaymentInitiation, ProviderVerification
from bot.models.subscriptions import SubscriptionStatus
from bot.services.access import AccessService, AccessUnavailable
from bot.services.admin_plans import AdminPlanService
from bot.services.payments import PaymentSettlementError
from bot.services.subscriptions import SubscriptionService


@skipUnless(os.getenv("PAPILIO_TEST_DATABASE_URL"), "Requires an explicitly configured MySQL URL")
class MysqlRepositoryTests(IsolatedAsyncioTestCase):
    async def test_catalog_and_order_roundtrip_with_rollback(self) -> None:
        repository = MysqlSubscriptionRepository(os.environ["PAPILIO_TEST_DATABASE_URL"])
        payments = MysqlPaymentRepository(os.environ["PAPILIO_TEST_DATABASE_URL"])
        access_repository = MysqlAccessRepository(
            os.environ["PAPILIO_TEST_DATABASE_URL"], Fernet.generate_key().decode()
        )
        code = "test_" + uuid4().hex
        owner = -(uuid4().int % 2**40 + 1)
        try:
            await repository.initialize()
            async with repository._engine.connect() as connection:
                transaction = await connection.begin()
                original_factory = repository._session_factory
                original_payments_factory = payments._session_factory
                original_access_factory = access_repository._session_factory
                test_factory = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
                )
                repository._session_factory = test_factory
                payments._session_factory = test_factory
                access_repository._session_factory = test_factory
                try:
                    admin = AdminPlanService(repository, frozenset({owner}))
                    customer = SubscriptionService(repository, repository)
                    plan = await admin.save_plan(
                        owner,
                        code=code,
                        title="آزمون برگشت‌پذیر",
                        traffic_gb=17,
                        duration_days=21,
                        price_rial=123_450,
                        sort_order=99,
                        emoji="🪐",
                    )
                    self.assertFalse(plan.is_active)
                    saved = await repository.get(code)
                    assert saved is not None
                    self.assertEqual(saved.emoji, "🪐")
                    await repository.update_prices({code: 133_450}, {code: 123_450})
                    updated = await repository.get(code)
                    assert updated is not None
                    self.assertEqual(updated.price_rial, 133_450)
                    with self.assertRaises(ValueError):
                        await repository.update_prices({code: 143_450}, {code: 123_450})
                    await repository.update_prices({code: 123_450}, {code: 133_450})
                    self.assertNotIn(code, {item.code for item in await customer.list_plans()})
                    await admin.set_active(owner, code, True)
                    self.assertIn(code, {item.code for item in await customer.list_plans()})
                    await customer.register_user(TelegramUser(owner, "Integration test", None))
                    order = await customer.create_order(owner, code, Protocol.VMESS)
                    records = await customer.list_subscriptions(owner)
                    self.assertEqual(len(records), 1)
                    self.assertEqual(records[0].id, order.id)
                    self.assertEqual(records[0].price_rial, 123_450)
                    self.assertEqual(records[0].traffic_limit_bytes, 17 * 1024**3)
                    self.assertEqual(records[0].traffic_used_bytes, 0)
                    self.assertEqual(records[0].created_at.tzinfo, order.created_at.tzinfo)
                    self.assertEqual(await customer.list_subscriptions(owner - 1), [])
                    checkout = PaymentInitiation(
                        transaction_id="tx-" + uuid4().hex,
                        authority="auth-" + uuid4().hex,
                        amount_rial=order.price_rial,
                        payment_url="https://kpay.website/pay/test",
                    )
                    await payments.attach_checkout(order.id, checkout)
                    paid = ProviderVerification(
                        checkout.authority,
                        "paid",
                        checkout.transaction_id,
                        checkout.amount_rial,
                        "2026-10-01T00:00:00Z",
                    )
                    with self.assertRaises(PaymentSettlementError):
                        await payments.settle_verified(
                            ProviderVerification(
                                checkout.authority,
                                "paid",
                                checkout.transaction_id,
                                checkout.amount_rial + 10,
                                "2026-10-01T00:00:00Z",
                            )
                        )
                    self.assertTrue(await payments.settle_verified(paid))
                    self.assertTrue(await payments.settle_verified(paid))
                    settled = await customer.list_subscriptions(owner)
                    self.assertEqual(
                        settled[0].status, SubscriptionStatus.PAID_AWAITING_PROVISIONING
                    )
                    self.assertIn(
                        order.id,
                        {item.subscription_id for item in await access_repository.list_pending_paid()},
                    )
                    xray_id = "123e4567-e89b-42d3-a456-426614174000"
                    vless = f"vless://{xray_id}@node.example:443?security=reality#Papilio"
                    vmess = "vmess://" + base64.b64encode(
                        json.dumps({"id": xray_id, "add": "node.example"}).encode()
                    ).decode()
                    access_service = AccessService(access_repository)
                    activated_at = datetime.now(UTC)
                    access = await access_service.record_provisioned(
                        order.id, vless, vmess, activated_at
                    )
                    self.assertEqual(access.traffic_limit_bytes, 17 * 1024**3)
                    self.assertEqual(access.expires_at, activated_at + timedelta(days=21))
                    self.assertIn(
                        order.id,
                        {item.access.subscription_id for item in await access_repository.list_active_node_access()},
                    )
                    deliveries = await access_repository.claim_deliveries()
                    own_delivery = next(
                        item for item in deliveries if item.subscription_id == order.id
                    )
                    self.assertEqual(own_delivery.access.token, access.token)
                    await access_repository.mark_delivery_sent(order.id)
                    self.assertNotIn(
                        order.id,
                        {item.subscription_id for item in await access_repository.claim_deliveries()},
                    )
                    retry = await access_service.record_provisioned(
                        order.id, vless, vmess, activated_at
                    )
                    self.assertEqual(retry.token, access.token)
                    self.assertEqual(
                        (await customer.list_subscriptions(owner))[0].status,
                        SubscriptionStatus.ACTIVE,
                    )
                    self.assertTrue(await payments.settle_verified(paid))
                    ciphertext = await connection.scalar(
                        select(SubscriptionAccessModel.vless_ciphertext).where(
                            SubscriptionAccessModel.subscription_id == order.id
                        )
                    )
                    assert ciphertext is not None
                    self.assertNotIn(vless, ciphertext)
                    fetched = await access_service.get_by_token(access.token)
                    assert fetched is not None
                    self.assertEqual(fetched.vmess_link, vmess)
                    self.assertIsNone(await access_service.get_for_user(owner - 1, order.id))
                    exhausted = await access_service.record_usage(
                        order.id, 14 * 1024**3, 0, activated_at + timedelta(seconds=1)
                    )
                    self.assertFalse(exhausted)
                    alerts = await access_repository.claim_alerts()
                    self.assertEqual(len(alerts), 1)
                    self.assertEqual(alerts[0].telegram_id, owner)
                    await access_repository.mark_alert_sent(alerts[0].id)
                    self.assertEqual(await access_repository.claim_alerts(), [])
                    with self.assertRaises(AccessUnavailable):
                        await access_service.record_usage(
                            order.id, 13 * 1024**3, 0,
                            activated_at + timedelta(seconds=2),
                        )
                    self.assertTrue(await access_service.record_usage(
                        order.id, 17 * 1024**3, 0, activated_at + timedelta(seconds=3)
                    ))
                    self.assertNotIn(
                        order.id,
                        {item.access.subscription_id for item in await access_repository.list_active_node_access()},
                    )
                    with self.assertRaises(AccessUnavailable):
                        await access_service.get_by_token(access.token)
                finally:
                    await transaction.rollback()
                    repository._session_factory = original_factory
                    payments._session_factory = original_payments_factory
                    access_repository._session_factory = original_access_factory
            self.assertIsNone(await repository.get(code))
            self.assertEqual(await repository.list_for_user(owner), [])
        finally:
            await repository.close()
            await payments.close()
            await access_repository.close()


if __name__ == "__main__":
    import unittest

    unittest.main()
