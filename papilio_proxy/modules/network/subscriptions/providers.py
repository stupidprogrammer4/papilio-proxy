from aiogram import Bot
from dishka import Provider, Scope, provide

from papilio_proxy.config.database import DatabaseConnection
from papilio_proxy.config.settings import ConfigurationError, Settings
from papilio_proxy.modules.network.nodes.infra.client import XrayNodeClient
from papilio_proxy.modules.network.subscriptions.app.services import AccessService
from papilio_proxy.modules.network.subscriptions.infra.repository import MysqlAccessRepository
from papilio_proxy.modules.network.subscriptions.schedulers import (
    ProvisionDeliveryDispatcher,
    ProvisionDeliveryJob,
    UsageWarningDispatcher,
    UsageWarningJob,
)


class AccessProvider(Provider):
    scope = Scope.APP
    usage_job = provide(UsageWarningJob)
    delivery_job = provide(ProvisionDeliveryJob)

    @provide
    def warnings(self, repository: MysqlAccessRepository, bot: Bot) -> UsageWarningDispatcher:
        return UsageWarningDispatcher(repository, bot)

    @provide
    def deliveries(
        self, repository: MysqlAccessRepository, bot: Bot, settings: Settings, access: AccessService
    ) -> ProvisionDeliveryDispatcher:
        if not settings.subscription_public_base_url:
            raise ConfigurationError("آدرس عمومی اشتراک تنظیم نشده است.")
        return ProvisionDeliveryDispatcher(
            repository, bot, settings.subscription_public_base_url, access
        )

    @provide
    def repository(self, database: DatabaseConnection, settings: Settings) -> MysqlAccessRepository:
        if not settings.credential_encryption_key:
            raise ConfigurationError("کلید رمزگذاری اشتراک‌ها تنظیم نشده است.")
        return MysqlAccessRepository(database, settings.credential_encryption_key)

    @provide
    def service(
        self, repository: MysqlAccessRepository, node: XrayNodeClient | None
    ) -> AccessService:
        service = AccessService(repository)
        if node:
            service.node_links = node.hysteria_link
        return service
