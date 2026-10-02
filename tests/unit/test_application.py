from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from cryptography.fernet import Fernet
from dishka import make_async_container
from papilio.core.bootstrap import Bootstrapper

from papilio_proxy.config.database import DatabaseConnection
from papilio_proxy.config.providers import RuntimeProvider
from papilio_proxy.config.settings import Settings
from papilio_proxy.modules.accounts.admin.infra.repository import MysqlAdminWebRepository
from papilio_proxy.modules.network.subscriptions.infra.repository import MysqlAccessRepository
from papilio_proxy.modules.sales.payments.infra.repository import MysqlPaymentRepository
from papilio_proxy.modules.sales.subscriptions.infra.repository import MysqlSubscriptionRepository


class ApplicationTests(IsolatedAsyncioTestCase):
    async def test_native_module_discovery_uses_one_process_owned_mysql_pool(self) -> None:
        settings = Settings(
            None,
            "mysql+aiomysql://unused@localhost/test",
            frozenset(),
            None,
            Fernet.generate_key().decode(),
        )
        container = make_async_container(
            RuntimeProvider(settings), *Bootstrapper(["papilio_proxy.modules"]).boot_providers()
        )
        database = await container.get(DatabaseConnection)
        with patch.object(database, "dispose", new_callable=AsyncMock) as dispose:
            try:
                for kind in (
                    MysqlSubscriptionRepository,
                    MysqlPaymentRepository,
                    MysqlAccessRepository,
                    MysqlAdminWebRepository,
                ):
                    repository = await container.get(kind)
                    self.assertIs(repository._engine, database.engine)
                    await repository.close()
                self.assertEqual(database.engine.pool.size(), 5)
                dispose.assert_not_awaited()
            finally:
                await container.close()
            dispose.assert_awaited_once()
