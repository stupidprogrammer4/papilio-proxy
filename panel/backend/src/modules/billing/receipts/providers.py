from dishka import Provider, Scope, provide

from src.config.settings import PapilioSettings
from src.modules.billing.receipts.app.commands import PaymentReceiptCommand
from src.modules.billing.receipts.app.images import ReceiptImages
from src.modules.billing.receipts.infra.mysql import PaymentReceiptRepository
from src.modules.billing.receipts.interfaces import IPaymentReceiptCommand


class PaymentReceiptProvider(Provider):
    @provide(scope=Scope.APP)
    def images(self, settings: PapilioSettings) -> ReceiptImages:
        return ReceiptImages(settings.receipts)

    scope = Scope.REQUEST
    repo = provide(PaymentReceiptRepository)
    command = provide(PaymentReceiptCommand, provides=IPaymentReceiptCommand)
