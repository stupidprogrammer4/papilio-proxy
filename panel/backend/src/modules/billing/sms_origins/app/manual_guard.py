from papilio.errors.exceptions import ConflictException

from src.modules.billing.sms_origins.infra.financial import SmsFinancialReader
from src.modules.billing.sms_origins.interfaces import (
    IReceivingRealmService,
    ISmsOriginAdmissionService,
)


class SmsManualPaymentGuard:
    """Acquire only after Customer owners; never acquire a Customer here."""

    def __init__(
        self,
        reader: SmsFinancialReader,
        admission: ISmsOriginAdmissionService,
        realms: IReceivingRealmService,
    ) -> None:
        self.reader = reader
        self.admission = admission
        self.realms = realms

    async def acquire(self, topup_id: int) -> None:
        hint = await self.reader.binding_hint(topup_id)
        await self.admission.settlement_guard()
        if hint is not None and hint.receiving_realm_id is not None:
            await self.realms.locked(hint.receiving_realm_id)
        current = await self.reader.current_binding(topup_id)
        if hint != current:
            raise ConflictException(
                message="Receiving account changed; review this payment.",
                message_code="sms_payment_binding_changed",
                unique_dict={},
            )

    async def acquire_topup_creation(self) -> None:
        await self.admission.settlement_guard()
