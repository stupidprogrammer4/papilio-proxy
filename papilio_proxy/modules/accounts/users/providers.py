from dishka import Provider, Scope, provide

from papilio_proxy.config.database import DatabaseConnection
from papilio_proxy.modules.accounts.users.app.services import UserAccessService
from papilio_proxy.modules.accounts.users.infra.repository import MysqlUserAccessRepository
from papilio_proxy.modules.network.nodes.infra.client import XrayNodeClient


class UsersProvider(Provider):
    scope = Scope.APP

    @provide
    def repository(self, database: DatabaseConnection) -> MysqlUserAccessRepository:
        return MysqlUserAccessRepository(database)

    @provide
    def service(
        self, repository: MysqlUserAccessRepository, node: XrayNodeClient | None
    ) -> UserAccessService:
        return UserAccessService(repository, node)
