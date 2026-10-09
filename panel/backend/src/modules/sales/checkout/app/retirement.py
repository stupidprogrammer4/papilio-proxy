from typing import Literal

from papilio.errors.exceptions import NotFoundException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.sales.checkout.app.commands import now_naive
from src.modules.sales.checkout.domain.attempts import (
    CheckoutRetire,
    CheckoutRetirement,
)
from src.modules.sales.checkout.domain.contracts import CheckoutRead
from src.modules.sales.checkout.domain.models import CheckoutIntentModel
from src.modules.sales.checkout.infra.mysql import CheckoutIntentRepository
from src.modules.sales.checkout.interfaces import (
    ICheckoutAttemptService,
    ICheckoutNoticeCommand,
)


class CheckoutRetirementCommand:
    """Explicit owner cancellation fences even a delayed create handler."""

    def __init__(
        self,
        customers: ICustomerService,
        attempts: ICheckoutAttemptService,
        intents: CheckoutIntentRepository,
        notices: ICheckoutNoticeCommand,
    ) -> None:
        self.notices = notices
        self.attempts, self.intents = attempts, intents
        self.customers = customers

    @handle_conflicts(message_code="checkout_request_conflict")
    @transactional
    async def retire(
        self, customer_id: int, data: CheckoutRetire
    ) -> CheckoutRetirement:
        key = f"checkout:{customer_id}:{data.request_key}"
        # Lock the FK parent exclusively before inserting a reservation.
        # This avoids two independent keys upgrading shared Customer locks,
        # and matches the worker's Customer -> reservation -> intent order.
        await self.customers.locked(customer_id)
        reservation = await self.attempts.reserve(customer_id, key, None)
        intent = await self.intents.by_request_key_current(key)
        if intent is not None and intent.customer_id != customer_id:
            raise NotFoundException(
                message="Checkout request not found",
                message_code="checkout_not_found",
                entity="checkout",
                identifier="request_key",
                identifier_value=data.request_key,
            )
        await self.attempts.retire(reservation)
        status: Literal["retired", "purchased"] = "retired"
        if intent is not None:
            await self.attempts.link(
                reservation, intent.id, intent.body_sha256
            )
            if (
                intent.subscription_id is not None
                or intent.state == "purchased"
            ):
                status = "purchased"
            elif intent.state not in {"cancelled", "expired"}:
                intent = await self.intents.update_existing(
                    intent,
                    CheckoutIntentModel.patch(
                        revision=intent.revision + 1,
                        state="cancelled",
                        reason_code="checkout_attempt_retired",
                        checked_at=now_naive(),
                    ),
                )
                await self.notices.capture(intent)
        return CheckoutRetirement(
            request_key=data.request_key,
            status=status,
            intent=None
            if intent is None
            else CheckoutRead.model_validate(intent, from_attributes=True),
        )
