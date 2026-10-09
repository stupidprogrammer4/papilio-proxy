import asyncio

from papilio.errors.exceptions import ConflictException

from src.config.settings import PapilioSettings
from src.modules.billing.payment_identifiers.domain.contracts import (
    PERSISTED_RIAL_MAXIMUM,
    RIAL_SUFFIX_MODULUS,
    PaymentAmountAllocation,
    PaymentAmountFacts,
    PaymentIdentifierPolicy,
)
from src.modules.billing.payment_identifiers.infra.readers import (
    PaymentAmountReader,
)


def allocation_conflict(code: str) -> ConflictException:
    return ConflictException(
        message="Payment amount identifier is unavailable.",
        message_code=code,
        unique_dict={},
    )


def choose_amount(
    requested: int,
    maximum: int,
    facts: PaymentAmountFacts,
    amount_step_rial: int,
) -> PaymentAmountAllocation:
    historical, active = set(facts.historical_amounts), set(facts.active_codes)
    minimum_payable = (
        (requested + amount_step_rial - 1) // amount_step_rial
    ) * amount_step_rial
    candidate = next(
        (
            amount
            for amount in range(minimum_payable, maximum + 1, amount_step_rial)
            if amount not in historical
            and amount % RIAL_SUFFIX_MODULUS not in active
        ),
        None,
    )
    if candidate is None:
        raise allocation_conflict("payment_identifier_exhausted")
    return PaymentAmountAllocation(
        requested,
        candidate,
        "rial_suffix4",
        f"{candidate % RIAL_SUFFIX_MODULUS:04d}",
        True,
    )


class PaymentAmountAllocationQuery:
    def __init__(
        self, reader: PaymentAmountReader, settings: PapilioSettings
    ) -> None:
        self.reader, self.settings = reader, settings

    async def allocate(
        self,
        requested: int,
        realm_id: int,
        policy: PaymentIdentifierPolicy,
        maximum_topup_rial: int,
    ) -> PaymentAmountAllocation:
        capacity = self.settings.checkout.payment_identifier_capacity
        if capacity is None:
            raise allocation_conflict("payment_identifier_disabled")
        if policy.max_adjustment_rial > capacity.max_adjustment_rial:
            raise allocation_conflict("payment_identifier_capacity")
        maximum = min(
            requested + policy.max_adjustment_rial,
            maximum_topup_rial,
            self.settings.checkout.maximum_topup_rial,
            PERSISTED_RIAL_MAXIMUM,
        )
        if (
            maximum < requested
            or ((maximum - requested) // policy.amount_step_rial) + 1
            > capacity.max_candidate_amounts
        ):
            raise allocation_conflict("payment_identifier_candidate_capacity")
        facts = await self.reader.facts(
            realm_id,
            requested,
            maximum,
            capacity.max_candidate_amounts + 1,
            capacity.max_active_codes + 1,
            policy.amount_step_rial,
            "pending",
        )
        if (
            len(facts.historical_amounts) > capacity.max_candidate_amounts
            or len(facts.active_codes) >= capacity.max_active_codes
        ):
            raise allocation_conflict("payment_identifier_capacity")
        result = await asyncio.to_thread(
            choose_amount, requested, maximum, facts, policy.amount_step_rial
        )
        return result
