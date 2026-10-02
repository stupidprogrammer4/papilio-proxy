from __future__ import annotations

import os
from unittest import IsolatedAsyncioTestCase, skipUnless

from sqlalchemy.ext.asyncio import async_sessionmaker

from papilio_proxy.modules.sales.pricing.domain.entities import PricingAssumptions
from papilio_proxy.modules.sales.pricing.infra.repository import MysqlPricingRepository


@skipUnless(os.getenv("PAPILIO_TEST_DATABASE_URL"), "Requires an explicitly configured MySQL URL")
class PricingMysqlTests(IsolatedAsyncioTestCase):
    async def test_assumptions_roundtrip_with_rollback(self) -> None:
        repository = MysqlPricingRepository(os.environ["PAPILIO_TEST_DATABASE_URL"])
        await repository.initialize()
        try:
            original = await repository.get()
            async with repository._engine.connect() as connection:
                transaction = await connection.begin()
                factory = repository._sessions
                repository._sessions = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
                )
                try:
                    value = PricingAssumptions(30, 800_000, 900, 3_500, 25, 1_000, 2_500)
                    await repository.save(value)
                    self.assertEqual(await repository.get(), value)
                finally:
                    await transaction.rollback()
                    repository._sessions = factory
            self.assertEqual(await repository.get(), original)
        finally:
            await repository.close()
