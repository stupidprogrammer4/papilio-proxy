from dishka import Provider, Scope, provide

from papilio_proxy.config.database import DatabaseConnection
from papilio_proxy.modules.brand.profile.app.services import BrandingService
from papilio_proxy.modules.brand.profile.infra.repository import MysqlBrandingRepository


class BrandingProvider(Provider):
    scope = Scope.APP

    @provide
    def service(self, repository: MysqlBrandingRepository) -> BrandingService:
        return BrandingService(repository)

    @provide
    def repository(self, database: DatabaseConnection) -> MysqlBrandingRepository:
        return MysqlBrandingRepository(database)
