from datetime import timedelta

from papilio.errors.exceptions import ConflictException, NotFoundException
from papilio.infra.db.transaction import active_transaction

from src.modules.sales.checkout.app.commands import now_naive
from src.modules.sales.checkout.domain.contracts import CheckoutCapacity
from src.modules.sales.checkout.domain.models import CheckoutIntentModel
from src.modules.sales.checkout.infra.mysql import CheckoutIntentRepository
from src.modules.sales.checkout.interfaces import (
    ICheckoutIntentCommand,
    IPurchaseCheckoutPolicyQuery,
)


class CheckoutRecoveryRunner:
    def __init__(self, command: ICheckoutIntentCommand) -> None:
        self.command = command

    async def run(self, id: int) -> CheckoutIntentModel:
        if active_transaction() is not None:
            raise RuntimeError(
                "Checkout recovery requires an outer native operation"
            )
        try:
            result = await self.command.attempt(id)
        except (ConflictException, NotFoundException) as error:
            if active_transaction() is not None:
                raise RuntimeError(
                    "Failed checkout transaction is still active"
                ) from error
            result = await self.command.record_failure(id, error.message_code)
        return result


class CheckoutRecoveryQuery:
    def __init__(
        self,
        intents: CheckoutIntentRepository,
        capacity: CheckoutCapacity,
        policies: IPurchaseCheckoutPolicyQuery,
    ) -> None:
        self.intents, self.capacity, self.policies = (
            intents,
            capacity,
            policies,
        )

    async def due_ids(
        self, limit: int | None = None, recheck_seconds: int | None = None
    ) -> list[int]:
        if not (await self.policies.current()).enabled:
            return []
        result = await self.intents.due_ids(
            ["awaiting_funding", "ready", "action_required"],
            now_naive()
            - timedelta(
                seconds=recheck_seconds or self.capacity.recheck_seconds
            ),
            min(limit or self.capacity.scan_limit, self.capacity.scan_limit),
        )
        return result
