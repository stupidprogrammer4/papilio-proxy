from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.billing.destinations.domain.dtos import (
    CheckoutPolicy,
    DestinationSearch,
)
from src.modules.billing.destinations.domain.results import (
    DestinationDetails,
    PaymentInstruction,
)
from src.modules.bot.domain.dtos import BotIdentity
from src.modules.operations.notifications.domain.context import (
    CheckoutNoticeAction,
)
from src.modules.operations.preferences.domain.dtos import BusinessPreferences
from src.modules.sales.catalog.domain.models import PlanModel
from src.modules.sales.checkout.domain.attempts import (
    CheckoutAttemptModel,
    CheckoutRetire,
    CheckoutRetirement,
)
from src.modules.sales.checkout.domain.contracts import (
    CheckoutCancel,
    CheckoutCreate,
    CheckoutLookup,
    CheckoutOffer,
    CheckoutPaymentInstructionRead,
    CheckoutRead,
    CheckoutReconfirm,
    CheckoutSearch,
    PurchaseCheckoutPolicy,
)
from src.modules.sales.checkout.domain.models import CheckoutIntentModel
from src.modules.sales.loyalty.domain.results import CustomerPriceQuote


class ICheckoutOfferQuery(Protocol):
    def get(
        self, customer_id: int, plan_id: int
    ) -> Awaitable[CheckoutOffer]: ...


class ICheckoutIntentCommand(Protocol):
    def create(
        self, customer_id: int, data: CheckoutCreate
    ) -> Awaitable[CheckoutIntentModel]: ...
    def reconfirm(
        self, customer_id: int, id: int, data: CheckoutReconfirm
    ) -> Awaitable[CheckoutIntentModel]: ...
    def cancel(
        self, customer_id: int, id: int, data: CheckoutCancel
    ) -> Awaitable[CheckoutIntentModel]: ...
    def attempt(self, id: int) -> Awaitable[CheckoutIntentModel]: ...
    def record_failure(
        self, id: int, code: str
    ) -> Awaitable[CheckoutIntentModel]: ...


class ICheckoutIntentLockCommand(Protocol):
    def owned(
        self, customer_id: int, id: int
    ) -> Awaitable[CheckoutIntentModel]: ...

    def known(self, id: int) -> Awaitable[CheckoutIntentModel]: ...


class ICheckoutRecoveryQuery(Protocol):
    def due_ids(
        self, limit: int | None = None, recheck_seconds: int | None = None
    ) -> Awaitable[list[int]]: ...


class ICheckoutRecoveryRunner(Protocol):
    def run(self, id: int) -> Awaitable[CheckoutIntentModel]: ...


class ICheckoutActionReceiptService(Protocol):
    def replay(
        self,
        row: CheckoutIntentModel,
        action: str,
        data: CheckoutReconfirm | CheckoutCancel,
    ) -> Awaitable[tuple[str, str, bool]]: ...
    def record(
        self, row: CheckoutIntentModel, action: str, key: str, digest: str
    ) -> Awaitable[None]: ...


class ICheckoutQuery(Protocol):
    def lookup(
        self, customer_id: int, data: CheckoutLookup
    ) -> Awaitable[CheckoutRead]: ...

    def search(
        self, customer_id: int, data: CheckoutSearch
    ) -> Awaitable[ServicePage[CheckoutRead]]: ...

    def get(self, customer_id: int, id: int) -> Awaitable[CheckoutRead]: ...


class ICheckoutFundingQuery(Protocol):
    def policy(self) -> Awaitable[CheckoutPolicy]: ...


class ICheckoutFundingPublisher(Protocol):
    def publish(self, topup_id: int) -> Awaitable[bool]: ...


class ICheckoutTaskPublisher(Protocol):
    def enqueue(self, id: int) -> Awaitable[bool]: ...


class ICheckoutProductVerifier(Protocol):
    def verify(
        self,
        customer_id: int,
        plan: PlanModel,
        quote: CustomerPriceQuote,
        values: BusinessPreferences,
        expected_sha256: str,
    ) -> Awaitable[None]: ...


class ICheckoutBotCommand(Protocol):
    def retire(
        self, identity: BotIdentity, data: CheckoutRetire
    ) -> Awaitable[CheckoutRetirement]: ...

    def payment_instruction(
        self, identity: BotIdentity, id: int
    ) -> Awaitable[CheckoutPaymentInstructionRead | None]: ...

    def funding(self, identity: BotIdentity) -> Awaitable[CheckoutPolicy]: ...
    def destinations(
        self, identity: BotIdentity, data: DestinationSearch
    ) -> Awaitable[ServicePage[DestinationDetails]]: ...
    def instruction(
        self, identity: BotIdentity, id: int
    ) -> Awaitable[PaymentInstruction]: ...

    def lookup(
        self, identity: BotIdentity, data: CheckoutLookup
    ) -> Awaitable[CheckoutRead]: ...

    def search(
        self, identity: BotIdentity, data: CheckoutSearch
    ) -> Awaitable[ServicePage[CheckoutRead]]: ...

    def offer(
        self, identity: BotIdentity, plan_id: int
    ) -> Awaitable[CheckoutOffer]: ...
    def get(
        self, identity: BotIdentity, id: int
    ) -> Awaitable[CheckoutRead]: ...
    def create(
        self, identity: BotIdentity, data: CheckoutCreate
    ) -> Awaitable[CheckoutRead]: ...
    def reconfirm(
        self, identity: BotIdentity, id: int, data: CheckoutReconfirm
    ) -> Awaitable[CheckoutRead]: ...
    def cancel(
        self, identity: BotIdentity, id: int, data: CheckoutCancel
    ) -> Awaitable[CheckoutRead]: ...


class IPurchaseCheckoutPolicyQuery(Protocol):
    def current(
        self, *, locked: bool = False
    ) -> Awaitable[PurchaseCheckoutPolicy]: ...


class ICheckoutAttemptService(Protocol):
    def reserve(
        self, customer_id: int, key: str, digest: str | None
    ) -> Awaitable[CheckoutAttemptModel]: ...
    def admit(self, row: CheckoutAttemptModel, digest: str) -> None: ...
    def link(
        self, row: CheckoutAttemptModel, intent_id: int, digest: str
    ) -> Awaitable[None]: ...
    def retire(self, row: CheckoutAttemptModel) -> Awaitable[None]: ...


class ICheckoutRetirementCommand(Protocol):
    def retire(
        self, customer_id: int, data: CheckoutRetire
    ) -> Awaitable[CheckoutRetirement]: ...


class ICheckoutNoticeCommand(Protocol):
    def capture(self, intent: CheckoutIntentModel) -> Awaitable[None]: ...


class ICheckoutNoticeSourceQuery(Protocol):
    def owned(
        self, customer_id: int, id: int
    ) -> Awaitable[CheckoutNoticeAction | None]: ...
