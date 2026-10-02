from dishka import Provider, Scope, provide

from papilio_proxy.config.database import DatabaseConnection
from papilio_proxy.modules.sales.pricing.app.services import PricingService
from papilio_proxy.modules.sales.pricing.infra.repository import MysqlPricingRepository


class PricingProvider(Provider):
    scope = Scope.APP

    @provide
    def repository(self, database: DatabaseConnection) -> MysqlPricingRepository:
        return MysqlPricingRepository(database)

    @provide
    def service(self, repository: MysqlPricingRepository) -> PricingService:
        return PricingService(repository)
