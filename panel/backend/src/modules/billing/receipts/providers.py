from dishka import Provider, Scope, provide

from src.config.settings import PapilioSettings
from src.modules.billing.receipts.app.annotation_interfaces import (
    IReceiptAnnotationCommand,
)
from src.modules.billing.receipts.app.annotations import (
    ReceiptAnnotationCommand,
)
from src.modules.billing.receipts.app.commands import PaymentReceiptCommand
from src.modules.billing.receipts.app.images import ReceiptImages
from src.modules.billing.receipts.app.ocr_commands import (
    PaymentReceiptOcrCommand,
)
from src.modules.billing.receipts.app.ocr_interfaces import (
    IPaymentReceiptOcrCommand,
    IReceiptOcrApi,
)
from src.modules.billing.receipts.app.outbox_commands import (
    PaymentReceiptOutboxCommand,
)
from src.modules.billing.receipts.app.outbox_interfaces import (
    IPaymentReceiptOutboxCommand,
    IReceiptOcrEventPublisher,
)
from src.modules.billing.receipts.infra.google_vision import (
    GoogleVisionReceiptOcr,
)
from src.modules.billing.receipts.infra.mysql import (
    PaymentReceiptAnnotationRepository,
    PaymentReceiptOutboxRepository,
    PaymentReceiptRepository,
)
from src.modules.billing.receipts.interfaces import IPaymentReceiptCommand
from src.modules.billing.receipts.tasks.events import ReceiptOcrConsumer
from src.modules.billing.receipts.tasks.publishers import (
    JetStreamReceiptOcrEventPublisher,
)
from src.modules.billing.receipts.tasks.schedulers.outbox import (
    PublishReceiptOcrOutbox,
)


class PaymentReceiptProvider(Provider):
    @provide(scope=Scope.APP)
    def images(self, settings: PapilioSettings) -> ReceiptImages:
        return ReceiptImages(settings.receipts)

    @provide(scope=Scope.APP)
    def ocr_api(self, settings: PapilioSettings) -> IReceiptOcrApi:
        return GoogleVisionReceiptOcr(settings.receipts)

    @provide(scope=Scope.APP)
    def ocr_publisher(self) -> IReceiptOcrEventPublisher:
        return JetStreamReceiptOcrEventPublisher()

    scope = Scope.REQUEST
    repo = provide(PaymentReceiptRepository)
    annotation_repo = provide(PaymentReceiptAnnotationRepository)
    outbox_repo = provide(PaymentReceiptOutboxRepository)
    command = provide(PaymentReceiptCommand, provides=IPaymentReceiptCommand)
    annotation_command = provide(
        ReceiptAnnotationCommand, provides=IReceiptAnnotationCommand
    )
    outbox_command = provide(
        PaymentReceiptOutboxCommand, provides=IPaymentReceiptOutboxCommand
    )
    ocr_command = provide(
        PaymentReceiptOcrCommand, provides=IPaymentReceiptOcrCommand
    )
    ocr_consumer = provide(ReceiptOcrConsumer, scope=Scope.REQUEST)
    outbox_task = provide(PublishReceiptOcrOutbox, scope=Scope.REQUEST)
