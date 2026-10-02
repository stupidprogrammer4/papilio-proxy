from dishka import Provider, Scope, provide

from papilio_proxy.config.database import DatabaseConnection
from papilio_proxy.modules.analytics.dashboard.app.services import DashboardService
from papilio_proxy.modules.analytics.dashboard.infra.repository import MysqlDashboardRepository


class DashboardProvider(Provider):
    scope = Scope.APP

    @provide
    def repository(self, database: DatabaseConnection) -> MysqlDashboardRepository:
        return MysqlDashboardRepository(database)

    @provide
    def service(self, repository: MysqlDashboardRepository) -> DashboardService:
        return DashboardService(repository)
