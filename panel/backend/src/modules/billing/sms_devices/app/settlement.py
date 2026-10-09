from datetime import UTC, datetime, timedelta

from papilio.infra.db.tools.decorators import transactional

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.billing.destinations.infra.mysql import (
    PaymentDestinationRepository,
)
from src.modules.billing.sms.infra.mysql import SmsRepository
from src.modules.billing.sms_devices.domain.settlement import (
    SmsSettlementOwnerHint,
)
from src.modules.billing.sms_devices.infra.mysql import SmsDeviceRepository
from src.modules.billing.sms_devices.infra.settlement import (
    SmsSettlementReader,
)
from src.modules.billing.sms_origins.interfaces import (
    ISmsOriginAdmissionService,
    ISmsOriginSettlementCommand,
)
from src.modules.billing.wallet.infra.mysql import TopupRepository
from src.modules.billing.wallet.interfaces import IWalletCommand


class SmsSettlementCommand:
    def __init__(
        self,
        messages: SmsRepository,
        devices: SmsDeviceRepository,
        reader: SmsSettlementReader,
        topups: TopupRepository,
        wallets: IWalletCommand,
        settings: PapilioSettings,
        destinations: PaymentDestinationRepository,
        customers: ICustomerService,
        admission: ISmsOriginAdmissionService,
        origins: ISmsOriginSettlementCommand,
    ) -> None:
        self.messages, self.devices, self.reader = messages, devices, reader
        self.topups, self.wallets, self.settings = topups, wallets, settings
        self.destinations = destinations
        self.customers = customers
        self.admission = admission
        self.origins = origins

    @transactional
    async def check_event(
        self, event_id: str, *, expected_topup_id: int | None = None
    ) -> str:
        policy = self.settings.sms_devices
        event = await self.messages.by_event_id(event_id)
        if event is None or event.device_id is None:
            return "manual"
        source = await self.devices.get_by_id(event.device_id)
        if source is None or source.destination_id is None:
            return "manual"
        if (
            event.parser_revision_id is not None
            or event.receiving_realm_id is not None
            or source.parser_profile_id is not None
            or source.settlement_identity_mode != "bank_reference_required"
        ):
            # Configured observations require the modern current-policy path.
            # They must never inherit legacy approval decisions.
            result = await self.origins.check_event(
                event_id, expected_topup_id=expected_topup_id
            )
            return result
        if policy is None or not policy.enabled:
            return "manual"
        if event.bank_reference is None or event.amount_rial is None:
            return "manual"
        now = datetime.now(UTC).replace(tzinfo=None)
        operations = self.settings.operations
        window = timedelta(hours=operations.sms_match_window_hours)
        grace = timedelta(minutes=operations.sms_match_before_topup_minutes)
        hints: list[SmsSettlementOwnerHint] = []
        if now - window <= event.sent_at <= now:
            hints = await self.reader.owner_hints(
                source.destination_id,
                event.amount_rial,
                event.sent_at - window,
                event.sent_at + grace,
                "pending",
                policy.max_match_candidates + 1,
            )
        hint = hints[0] if len(hints) == 1 else None
        # This hint grants no approval. Lock the FK owner first, then repeat
        # all destination/device/payment/SMS decisions using current facts.
        if hint is not None:
            await self.customers.locked(hint.customer_id)
        await self.admission.settlement_guard()
        # Serialize receiving-account decisions before locking devices.
        destination = await self.destinations.locked(source.destination_id)
        if destination is None or not destination.is_active:
            return "manual"
        device = await self.devices.locked(event.device_id)
        now = datetime.now(UTC).replace(tzinfo=None)
        if (
            device is None
            or not device.is_active
            or device.expires_at <= now
            or device.approval_mode != "unique_sms"
            or device.destination_id != destination.id
        ):
            return "manual"
        if not now - window <= event.sent_at <= now:
            return "outside_window"
        # A non-approval path still reports the current source's eligibility,
        # but never acquires a Customer after Destination/Device locks.
        if hint is None:
            return "ambiguous" if len(hints) > 1 else "waiting"
        if (
            expected_topup_id is not None
            and hint.topup_id != expected_topup_id
        ):
            return "waiting"
        facts = await self.reader.matches(
            destination.id,
            event.amount_rial,
            event.sent_at - window,
            event.sent_at + grace,
            now - window,
            now,
            "pending",
            "approved",
            "unique_sms",
            True,
            now,
            policy.max_match_candidates + 1,
        )
        if (
            len(facts.topups) > 1
            or len(facts.messages) > policy.max_match_candidates
        ):
            return "ambiguous"
        references = {row.bank_reference for row in facts.messages}
        if len(references) > 1:
            return "ambiguous"
        if not facts.topups or not facts.messages:
            return "waiting"
        (topup,) = facts.topups
        if topup.id != hint.topup_id or topup.customer_id != hint.customer_id:
            # Never acquire a changed Customer after Destination/Topup locks.
            return "waiting"
        if expected_topup_id is not None and topup.id != expected_topup_id:
            return "waiting"
        assert topup.created_at is not None
        eligible = [
            row
            for row in facts.messages
            if row.sent_at >= topup.created_at - grace
        ]
        if not eligible:
            return "waiting"
        # Duplicate delivery records for one bank reference share its earliest
        # persisted authenticated event as the explicit provenance identity.
        selected = min(eligible, key=lambda message: message.id)
        assert (
            selected.bank_reference is not None
            and selected.device_id is not None
        )
        await self.wallets.approve_from_sms(
            topup.id, selected.id, selected.device_id, selected.bank_reference
        )
        return "approved"

    async def check_topup(self, topup_id: int) -> str:
        policy = self.settings.sms_devices
        topup = await self.topups.get_by_id(topup_id)
        if (
            policy is None
            or not policy.enabled
            or topup is None
            or topup.status != "pending"
            or topup.destination_id is None
        ):
            return "manual"
        now = datetime.now(UTC).replace(tzinfo=None)
        event_ids = await self.reader.event_ids(
            topup.destination_id,
            topup.amount_rial,
            now
            - timedelta(hours=self.settings.operations.sms_match_window_hours),
            now,
            "unique_sms",
            True,
            now,
            policy.max_match_candidates + 1,
        )
        if not event_ids:
            return "waiting"
        if len(event_ids) > policy.max_match_candidates:
            return "ambiguous"
        # A recovery check keeps the requested payment identity throughout.
        result = await self.check_event(
            min(event_ids), expected_topup_id=topup_id
        )
        return result

    @transactional
    async def approved_topup_for_event(
        self, event_id: str, device_id: int
    ) -> int | None:
        result = await self.reader.approved_topup_for_event(
            event_id, device_id, "approved"
        )
        return result
