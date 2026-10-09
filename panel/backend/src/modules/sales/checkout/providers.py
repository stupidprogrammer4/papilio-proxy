from dishka import Provider, Scope, provide

from src.config.settings import PapilioSettings
from src.modules.sales.checkout.app.attempts import CheckoutAttemptService
from src.modules.sales.checkout.app.bot import CheckoutBotCommand
from src.modules.sales.checkout.app.commands import CheckoutIntentCommand
from src.modules.sales.checkout.app.funding import CheckoutFundingQuery
from src.modules.sales.checkout.app.locking import CheckoutIntentLockCommand
from src.modules.sales.checkout.app.notices import (
    CheckoutNoticeCommand,
    CheckoutNoticeSourceQuery,
)
from src.modules.sales.checkout.app.offers import CheckoutOfferQuery
from src.modules.sales.checkout.app.policy_query import (
    PurchaseCheckoutPolicyQuery,
)
from src.modules.sales.checkout.app.publication import (
    CheckoutFundingPublisher,
    CheckoutTaskPublisher,
)
from src.modules.sales.checkout.app.queries import CheckoutQuery
from src.modules.sales.checkout.app.receipts import (
    CheckoutActionReceiptService,
)
from src.modules.sales.checkout.app.recovery import (
    CheckoutRecoveryQuery,
    CheckoutRecoveryRunner,
)
from src.modules.sales.checkout.app.retirement import CheckoutRetirementCommand
from src.modules.sales.checkout.app.verifier import CheckoutProductVerifier
from src.modules.sales.checkout.domain.contracts import CheckoutCapacity
from src.modules.sales.checkout.infra.attempts import CheckoutAttemptRepository
from src.modules.sales.checkout.infra.mysql import (
    CheckoutActionReceiptRepository,
    CheckoutIntentRepository,
)
from src.modules.sales.checkout.infra.readers import (
    CheckoutFundingReader,
    CheckoutOfferReader,
)
from src.modules.sales.checkout.interfaces import (
    ICheckoutActionReceiptService,
    ICheckoutAttemptService,
    ICheckoutBotCommand,
    ICheckoutFundingPublisher,
    ICheckoutFundingQuery,
    ICheckoutIntentCommand,
    ICheckoutIntentLockCommand,
    ICheckoutNoticeCommand,
    ICheckoutNoticeSourceQuery,
    ICheckoutOfferQuery,
    ICheckoutProductVerifier,
    ICheckoutQuery,
    ICheckoutRecoveryQuery,
    ICheckoutRecoveryRunner,
    ICheckoutRetirementCommand,
    ICheckoutTaskPublisher,
    IPurchaseCheckoutPolicyQuery,
)
from src.modules.sales.checkout.tasks.schedulers.recovery import (
    RecoverCheckout,
    ScanCheckouts,
)


class CheckoutProvider(Provider):
    scope = Scope.REQUEST

    @provide(scope=Scope.APP)
    def capacity(self, settings: PapilioSettings) -> CheckoutCapacity:
        return settings.purchase_intents or CheckoutCapacity()

    policy_query = provide(
        PurchaseCheckoutPolicyQuery, provides=IPurchaseCheckoutPolicyQuery
    )
    funding_query = provide(
        CheckoutFundingQuery, provides=ICheckoutFundingQuery
    )
    publisher = provide(CheckoutTaskPublisher, provides=ICheckoutTaskPublisher)
    funding_publisher = provide(
        CheckoutFundingPublisher, provides=ICheckoutFundingPublisher
    )
    recover_task = provide(RecoverCheckout)
    scan_task = provide(ScanCheckouts)
    bot = provide(CheckoutBotCommand, provides=ICheckoutBotCommand)
    intents = provide(CheckoutIntentRepository)
    attempts = provide(CheckoutAttemptRepository)
    attempt_service = provide(
        CheckoutAttemptService, provides=ICheckoutAttemptService
    )
    intent_locks = provide(
        CheckoutIntentLockCommand, provides=ICheckoutIntentLockCommand
    )
    retire = provide(
        CheckoutRetirementCommand, provides=ICheckoutRetirementCommand
    )
    receipts = provide(CheckoutActionReceiptRepository)
    offer_reader = provide(CheckoutOfferReader)
    funding_reader = provide(CheckoutFundingReader)
    action_receipts = provide(
        CheckoutActionReceiptService, provides=ICheckoutActionReceiptService
    )
    verifier = provide(
        CheckoutProductVerifier, provides=ICheckoutProductVerifier
    )
    offers = provide(CheckoutOfferQuery, provides=ICheckoutOfferQuery)
    notices = provide(CheckoutNoticeCommand, provides=ICheckoutNoticeCommand)
    notice_source = provide(
        CheckoutNoticeSourceQuery, provides=ICheckoutNoticeSourceQuery
    )
    command = provide(CheckoutIntentCommand, provides=ICheckoutIntentCommand)
    query = provide(CheckoutQuery, provides=ICheckoutQuery)
    recovery = provide(
        CheckoutRecoveryRunner, provides=ICheckoutRecoveryRunner
    )
    recovery_query = provide(
        CheckoutRecoveryQuery, provides=ICheckoutRecoveryQuery
    )
