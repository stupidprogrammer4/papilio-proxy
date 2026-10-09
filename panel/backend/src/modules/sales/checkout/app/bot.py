from src.config.pagination import ServicePage
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.billing.destinations.domain.dtos import (
    CheckoutPolicy,
    DestinationSearch,
)
from src.modules.billing.destinations.domain.results import (
    DestinationDetails,
    PaymentInstruction,
)
from src.modules.billing.destinations.interfaces import (
    IPaymentDestinationService,
)
from src.modules.billing.wallet.interfaces import ITopupInstructionQuery
from src.modules.bot.domain.dtos import BotIdentity
from src.modules.sales.checkout.domain.attempts import (
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
)
from src.modules.sales.checkout.interfaces import (
    ICheckoutFundingQuery,
    ICheckoutIntentCommand,
    ICheckoutOfferQuery,
    ICheckoutQuery,
    ICheckoutRetirementCommand,
    ICheckoutTaskPublisher,
)


class CheckoutBotCommand:
    def __init__(
        self,
        customers: ICustomerService,
        command: ICheckoutIntentCommand,
        offers: ICheckoutOfferQuery,
        query: ICheckoutQuery,
        publisher: ICheckoutTaskPublisher,
        funding: ICheckoutFundingQuery,
        destinations: IPaymentDestinationService,
        topup_instructions: ITopupInstructionQuery,
        retirement: ICheckoutRetirementCommand,
    ) -> None:
        self.customers, self.command, self.offers = customers, command, offers
        self.query, self.publisher = query, publisher
        self.funding_query, self.destination_service = funding, destinations
        self.topup_instructions = topup_instructions
        self.retirement = retirement

    async def retire(
        self, identity: BotIdentity, data: CheckoutRetire
    ) -> CheckoutRetirement:
        customer_id = await self.customer_id(identity)
        result = await self.retirement.retire(customer_id, data)
        return result

    async def customer_id(self, identity: BotIdentity) -> int:
        customer = await self.customers.ensure_telegram(
            identity.telegram_id, identity.display_name
        )
        return customer.id

    async def offer(
        self, identity: BotIdentity, plan_id: int
    ) -> CheckoutOffer:
        customer_id = await self.customer_id(identity)
        result = await self.offers.get(customer_id, plan_id)
        return result

    async def get(self, identity: BotIdentity, id: int) -> CheckoutRead:
        customer_id = await self.customer_id(identity)
        result = await self.query.get(customer_id, id)
        return result

    async def create(
        self, identity: BotIdentity, data: CheckoutCreate
    ) -> CheckoutRead:
        customer_id = await self.customer_id(identity)
        row = await self.command.create(customer_id, data)
        await self.publisher.enqueue(row.id)
        return CheckoutRead.model_validate(row, from_attributes=True)

    async def reconfirm(
        self, identity: BotIdentity, id: int, data: CheckoutReconfirm
    ) -> CheckoutRead:
        customer_id = await self.customer_id(identity)
        row = await self.command.reconfirm(customer_id, id, data)
        await self.publisher.enqueue(row.id)
        return CheckoutRead.model_validate(row, from_attributes=True)

    async def cancel(
        self, identity: BotIdentity, id: int, data: CheckoutCancel
    ) -> CheckoutRead:
        customer_id = await self.customer_id(identity)
        row = await self.command.cancel(customer_id, id, data)
        return CheckoutRead.model_validate(row, from_attributes=True)

    async def search(
        self, identity: BotIdentity, data: CheckoutSearch
    ) -> ServicePage[CheckoutRead]:
        customer_id = await self.customer_id(identity)
        result = await self.query.search(customer_id, data)
        return result

    async def lookup(
        self, identity: BotIdentity, data: CheckoutLookup
    ) -> CheckoutRead:
        customer_id = await self.customer_id(identity)
        result = await self.query.lookup(customer_id, data)
        return result

    async def funding(self, identity: BotIdentity) -> CheckoutPolicy:
        await self.customer_id(identity)
        result = await self.funding_query.policy()
        return result

    async def destinations(
        self, identity: BotIdentity, data: DestinationSearch
    ) -> ServicePage[DestinationDetails]:
        await self.customer_id(identity)
        result = await self.destination_service.search(data, customer=True)
        return result

    async def instruction(
        self, identity: BotIdentity, id: int
    ) -> PaymentInstruction:
        await self.customer_id(identity)
        result = await self.destination_service.instruction(id)
        return result

    async def payment_instruction(
        self, identity: BotIdentity, id: int
    ) -> CheckoutPaymentInstructionRead | None:
        customer_id = await self.customer_id(identity)
        intent = await self.query.get(customer_id, id)
        if intent.topup_id is None:
            return None
        result = await self.topup_instructions.get(
            intent.topup_id, customer_id
        )
        if result is None:
            return None
        return CheckoutPaymentInstructionRead(
            checkout_id=intent.id, **result.model_dump()
        )
