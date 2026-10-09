from datetime import UTC
from typing import Literal

from papilio.infra.db.tools.decorators import transactional
from pydantic import TypeAdapter

from src.config.settings import PapilioSettings
from src.modules.billing.destinations.interfaces import (
    IPaymentDestinationService,
)
from src.modules.billing.sms.infra.mysql import SmsRepository
from src.modules.billing.sms_devices.interfaces import ISmsDeviceService
from src.modules.billing.sms_origins.app.services import sms_not_found
from src.modules.billing.sms_origins.domain.contracts import (
    SmsSettlementReviewRead,
)
from src.modules.billing.sms_origins.infra.financial import SmsFinancialReader
from src.modules.billing.sms_origins.interfaces import (
    IReceivingRealmService,
    ISmsSettlementDecisionService,
    ISmsSettlementService,
)


class SmsSettlementReviewQuery:
    def __init__(
        self,
        messages: SmsRepository,
        devices: ISmsDeviceService,
        realms: IReceivingRealmService,
        destinations: IPaymentDestinationService,
        decisions: ISmsSettlementDecisionService,
        settlements: ISmsSettlementService,
        reader: SmsFinancialReader,
        settings: PapilioSettings,
    ) -> None:
        self.messages, self.devices, self.realms = messages, devices, realms
        self.destinations, self.decisions, self.settlements = (
            destinations,
            decisions,
            settlements,
        )
        self.settings = settings
        self.reader = reader

    async def get(self, id: int) -> SmsSettlementReviewRead:
        event = await self.messages.get_by_id(id)
        if event is None:
            raise sms_not_found("sms_not_found")
        device = (
            await self.devices.get(event.device_id)
            if event.device_id is not None
            else None
        )
        realm = (
            await self.realms.get(event.receiving_realm_id)
            if event.receiving_realm_id is not None
            else None
        )
        destination = (
            await self.destinations.get(event.captured_destination_id)
            if event.captured_destination_id is not None
            else None
        )
        decision = await self.decisions.get(id)
        settlement = await self.settlements.by_event(id)
        status = (
            "approved"
            if settlement is not None
            else decision.status
            if decision is not None
            else "manual"
        )
        reason = (
            None
            if settlement is not None
            else decision.reason_code
            if decision is not None
            else "sms_settlement_not_checked"
        )
        capacity = self.settings.sms_origins
        now = (await self.reader.utc_now()).replace(tzinfo=UTC)
        return SmsSettlementReviewRead(
            sms_event_id=id,
            device_id=event.device_id,
            device_revision=device.revision if device is not None else None,
            receiving_realm_id=event.receiving_realm_id,
            realm_revision=realm.revision if realm is not None else None,
            destination_id=event.captured_destination_id,
            destination_revision=destination.revision
            if destination is not None
            else None,
            status=TypeAdapter(
                Literal[
                    "manual",
                    "waiting",
                    "ambiguous",
                    "approved",
                    "outside_window",
                ]
            ).validate_python(status),
            reason_code=reason,
            checked_at=decision.checked_at.replace(tzinfo=UTC)
            if decision is not None
            else None,
            candidate_count=decision.candidate_count
            if decision is not None
            else 0,
            topup_id=settlement.topup_id
            if settlement is not None
            else decision.topup_id
            if decision is not None
            else None,
            settlement_id=settlement.id if settlement is not None else None,
            evidence_kind=TypeAdapter(
                Literal["bank_reference", "trusted_sms_origin"]
            ).validate_python(settlement.evidence_kind)
            if settlement is not None
            else None,
            manual_approval_available=capacity is not None
            and capacity.enabled
            and settlement is None
            and device is not None
            and device.is_active
            and device.expires_at > now
            and realm is not None
            and realm.is_active
            and destination is not None
            and destination.is_active
            and event.direction == "credit"
            and event.parse_reason_code is None,
        )


class SmsApprovedFundingQuery:
    def __init__(self, reader: SmsFinancialReader) -> None:
        self.reader = reader

    @transactional
    async def get(self, event_id: int) -> int | None:
        facts = await self.reader.funding(event_id)
        if facts is None or facts.topup_status != "approved":
            return None
        return facts.topup_id
