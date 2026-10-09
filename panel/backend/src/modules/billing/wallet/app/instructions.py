import asyncio

from papilio.errors.exceptions import NotFoundException
from papilio.security.crypto import decrypt
from pydantic import TypeAdapter

from src.config.settings import PapilioSettings
from src.modules.billing.destinations.domain.results import PaymentInstruction
from src.modules.billing.payment_identifiers.domain.contracts import (
    PaymentIdentifierMode,
)
from src.modules.billing.wallet.domain.results import (
    TopupPaymentInstructionRead,
)
from src.modules.billing.wallet.infra.mysql import TopupRepository


class TopupInstructionQuery:
    def __init__(
        self, repo: TopupRepository, settings: PapilioSettings
    ) -> None:
        self.repo = repo
        self.settings = settings

    async def get(
        self, id: int, customer_id: int | None = None
    ) -> TopupPaymentInstructionRead | None:
        row = await self.repo.get_by_id(id)
        if row is None or (
            customer_id is not None and row.customer_id != customer_id
        ):
            raise NotFoundException(
                message="درخواست شارژ پیدا نشد.",
                message_code="topup_not_found",
                entity="topup",
                identifier="id",
                identifier_value=id,
            )
        if row.encrypted_instruction is None:
            return None
        encrypted = row.encrypted_instruction
        decoded = await asyncio.to_thread(
            decrypt, encrypted, self.settings.configuration_encryption_key
        )
        instruction = PaymentInstruction.model_validate_json(decoded)
        return TopupPaymentInstructionRead(
            **instruction.model_dump(),
            topup_id=row.id,
            requested_amount_rial=row.requested_amount_rial
            if row.requested_amount_rial is not None
            else row.amount_rial,
            payable_amount_rial=row.amount_rial,
            payment_identifier_mode=TypeAdapter(
                PaymentIdentifierMode
            ).validate_python(row.payment_identifier_mode),
            payment_identifier_code4=row.payment_identifier_code4,
        )
