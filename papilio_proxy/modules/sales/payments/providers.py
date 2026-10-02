from dishka import Provider, Scope, provide

from papilio_proxy.config.database import DatabaseConnection
from papilio_proxy.config.settings import ConfigurationError, Settings
from papilio_proxy.modules.sales.payments.app.services import PaymentService
from papilio_proxy.modules.sales.payments.infra.repository import MysqlPaymentRepository
from papilio_proxy.modules.sales.payments.schedulers import ReceiptDecisionJob


class PaymentsProvider(Provider):
    scope = Scope.APP
    receipt_decisions = provide(ReceiptDecisionJob)

    @provide
    def repository(
        self, database: DatabaseConnection, settings: Settings
    ) -> MysqlPaymentRepository:
        if not settings.credential_encryption_key:
            raise ConfigurationError("کلید رمزگذاری رسیدها تنظیم نشده است.")
        return MysqlPaymentRepository(database, settings.credential_encryption_key)

    @provide
    def service(self, repository: MysqlPaymentRepository) -> PaymentService:
        return PaymentService(repository)
