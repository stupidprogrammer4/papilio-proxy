from dishka import Provider, Scope, provide

from papilio_proxy.config.database import DatabaseConnection
from papilio_proxy.config.settings import Settings
from papilio_proxy.modules.sales.subscriptions.app.plans import AdminPlanService
from papilio_proxy.modules.sales.subscriptions.app.services import SubscriptionService
from papilio_proxy.modules.sales.subscriptions.infra.repository import MysqlSubscriptionRepository


class SubscriptionsProvider(Provider):
    scope = Scope.APP

    @provide
    def repository(self, database: DatabaseConnection) -> MysqlSubscriptionRepository:
        return MysqlSubscriptionRepository(database)

    @provide
    def subscriptions(self, repository: MysqlSubscriptionRepository) -> SubscriptionService:
        return SubscriptionService(repository, repository)

    @provide
    def plans(
        self, repository: MysqlSubscriptionRepository, settings: Settings
    ) -> AdminPlanService:
        return AdminPlanService(repository, settings.admin_ids)
