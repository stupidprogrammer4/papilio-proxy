from dishka import Provider, Scope, provide

from papilio_proxy.config.database import DatabaseConnection
from papilio_proxy.modules.accounts.admin.app.services import AdminWebService
from papilio_proxy.modules.accounts.admin.infra.repository import MysqlAdminWebRepository
from papilio_proxy.modules.analytics.dashboard.app.services import DashboardService
from papilio_proxy.modules.brand.profile.app.services import BrandingService
from papilio_proxy.modules.sales.pricing.app.services import PricingService
from papilio_proxy.modules.sales.subscriptions.app.plans import AdminPlanService


class AdminProvider(Provider):
    scope = Scope.APP

    @provide
    def repository(self, database: DatabaseConnection) -> MysqlAdminWebRepository:
        return MysqlAdminWebRepository(database)

    @provide
    def service(
        self,
        repository: MysqlAdminWebRepository,
        dashboard: DashboardService,
        plans: AdminPlanService,
        branding: BrandingService,
        pricing: PricingService,
    ) -> AdminWebService:
        return AdminWebService(repository, dashboard, plans, branding, pricing)
