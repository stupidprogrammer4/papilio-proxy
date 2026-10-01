from __future__ import annotations

import os
from unittest import IsolatedAsyncioTestCase, skipUnless
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.infra.db.admin_web import MysqlAdminWebRepository
from bot.models.admin_web import AdminLoginDenied


@skipUnless(os.getenv("PAPILIO_TEST_DATABASE_URL"), "Requires an explicitly configured MySQL URL")
class AdminWebMysqlTests(IsolatedAsyncioTestCase):
    async def test_password_lockout_sessions_and_revocation_roll_back(self) -> None:
        repository = MysqlAdminWebRepository(os.environ["PAPILIO_TEST_DATABASE_URL"])
        await repository.initialize()
        username = "webtest_" + uuid4().hex[:12]
        try:
            async with repository._engine.connect() as connection:
                transaction = await connection.begin()
                original = repository._sessions
                repository._sessions = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
                )
                try:
                    await repository.set_password(username, "test-password-1")
                    finances = await repository.finances()
                    self.assertGreaterEqual(finances.settled_amount_rial, 0)
                    with self.assertRaises(AdminLoginDenied):
                        await repository.login(username, "wrong-password")
                    good = await repository.login(username, "test-password-1")
                    self.assertEqual(good.session.username, username)
                    stored = await repository.get_session(good.token)
                    assert stored is not None
                    self.assertEqual(stored.csrf_token, good.session.csrf_token)
                    await repository.logout(good.token)
                    self.assertIsNone(await repository.get_session(good.token))
                    second = await repository.login(username, "test-password-1")
                    await repository.set_password(username, "test-password-2")
                    self.assertIsNone(await repository.get_session(second.token))
                    with self.assertRaises(AdminLoginDenied):
                        await repository.login(username, "test-password-1")
                    await repository.login(username, "test-password-2")
                    for _ in range(5):
                        with self.assertRaises(AdminLoginDenied):
                            await repository.login(username, "wrong-password")
                    with self.assertRaises(AdminLoginDenied):
                        await repository.login(username, "test-password-2")
                finally:
                    await transaction.rollback()
                    repository._sessions = original
        finally:
            await repository.close()
