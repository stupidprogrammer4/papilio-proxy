import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from typing import Literal

from papilio.errors.exceptions import ConflictException
from papilio.infra.db.tools.decorators import transactional

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.billing.destinations.interfaces import (
    IPaymentDestinationService,
)
from src.modules.billing.sms.domain.models import SmsEventModel
from src.modules.billing.sms.infra.mysql import SmsRepository
from src.modules.billing.sms_devices.infra.mysql import SmsDeviceRepository
from src.modules.billing.sms_origins.app.association import legacy_associations
from src.modules.billing.sms_origins.app.parsing import normalize_origin_sender
from src.modules.billing.sms_origins.domain.contracts import (
    ManualSmsApproval,
    SmsSettlementProof,
)
from src.modules.billing.sms_origins.domain.models import (
    SmsSettlementDecisionModel,
    SmsSettlementModel,
)
from src.modules.billing.sms_origins.infra.financial import SmsFinancialReader
from src.modules.billing.sms_origins.interfaces import (
    IReceivingAliasService,
    IReceivingRealmService,
    ISmsOriginAdmissionService,
    ISmsParserProfileService,
    ISmsParserRevisionService,
    ISmsSettlementClaimService,
    ISmsSettlementDecisionService,
    ISmsSettlementService,
)
from src.modules.billing.wallet.interfaces import IWalletCommand


class SmsOriginSettlementCommand:
    def __init__(
        self,
        reader: SmsFinancialReader,
        messages: SmsRepository,
        devices: SmsDeviceRepository,
        customers: ICustomerService,
        admission: ISmsOriginAdmissionService,
        realms: IReceivingRealmService,
        aliases: IReceivingAliasService,
        destinations: IPaymentDestinationService,
        profiles: ISmsParserProfileService,
        revisions: ISmsParserRevisionService,
        settlements: ISmsSettlementService,
        claims: ISmsSettlementClaimService,
        decisions: ISmsSettlementDecisionService,
        wallets: IWalletCommand,
        settings: PapilioSettings,
    ) -> None:
        self.reader, self.messages, self.devices = (reader, messages, devices)
        self.customers, self.admission, self.realms = (
            customers,
            admission,
            realms,
        )
        self.aliases, self.destinations = (aliases, destinations)
        self.profiles, self.revisions = (profiles, revisions)
        self.settlements, self.claims, self.decisions = (
            settlements,
            claims,
            decisions,
        )
        self.wallets, self.settings = (wallets, settings)

    @transactional
    async def check_event(
        self,
        event_id: str,
        *,
        expected_topup_id: int | None = None,
        manual: ManualSmsApproval | None = None,
        staff_id: int | None = None,
    ) -> str:
        event = await self.messages.by_event_id(event_id)
        if event is None or event.device_id is None:
            return "manual"
        settled = await self.settlements.by_event(event.id)
        if settled is not None:
            if (
                expected_topup_id is not None
                and settled.topup_id != expected_topup_id
            ):
                raise ConflictException(
                    message="SMS belongs to another payment.",
                    message_code="sms_settlement_identity_used",
                    unique_dict={},
                )
            return "approved"
        capacity = self.settings.sms_origins
        if (
            capacity is None
            or not capacity.enabled
            or self.settings.sms_devices is None
            or not self.settings.sms_devices.enabled
        ):
            return "manual"
        now = await self.reader.utc_now()
        financial_at = (
            datetime(1970, 1, 1)
            + timedelta(milliseconds=event.original_provider_timestamp_ms)
            if event.original_provider_timestamp_ms is not None
            and event.origin_kind == "direct_sms"
            else event.sent_at
        )
        window = timedelta(
            hours=self.settings.operations.sms_match_window_hours
        )
        grace = timedelta(
            minutes=self.settings.operations.sms_match_before_topup_minutes
        )
        windows: list[
            tuple[list[str], Literal["created_at", "updated_at"]]
        ] = [(["pending"], "created_at"), (["approved"], "updated_at")]
        hints = (
            await self.reader.owner_hints(
                event.amount_rial,
                financial_at - window,
                financial_at + grace,
                windows,
                capacity.max_match_candidates + 1,
            )
            if capacity is not None
            and capacity.enabled
            and (event.amount_rial is not None)
            else []
        )
        if (
            capacity is not None
            and len(hints) <= capacity.max_match_candidates
        ):
            await self.customers.locked_many(
                sorted({item.customer_id for item in hints})
            )
        await self.admission.settlement_guard()
        previous = await self.settlements.by_event(event.id)
        if previous is not None:
            if (
                expected_topup_id is not None
                and previous.topup_id != expected_topup_id
            ):
                raise ConflictException(
                    message="SMS is linked to another payment.",
                    message_code="sms_settlement_identity_used",
                    unique_dict={},
                )
            return "approved"
        if capacity is None or not capacity.enabled:
            result = await self._decision(
                event, now, "manual", "sms_origins_unavailable"
            )
            return result
        if len(hints) > capacity.max_match_candidates:
            result = await self._decision(
                event, now, "manual", "sms_candidate_capacity"
            )
            return result
        if (
            event.receiving_realm_id is None
            or event.receiving_alias_id is None
            or event.captured_destination_id is None
        ):
            result = await self._decision(
                event, now, "manual", "sms_receiving_binding_missing"
            )
            return result
        realm = await self.realms.locked(event.receiving_realm_id)
        destination = await self.destinations.locked(
            event.captured_destination_id
        )
        device = await self.devices.locked(event.device_id)
        now = await self.reader.utc_now()
        if (
            device is None
            or not device.is_active
            or device.expires_at <= now
            or (manual is None and device.approval_mode != "unique_sms")
            or (device.destination_id != destination.destination_id)
            or (not realm.is_active)
            or (not destination.is_active)
            or (destination.revision != event.captured_destination_revision)
            or (destination.receiving_alias_id != event.receiving_alias_id)
        ):
            result = await self._decision(
                event, now, "manual", "sms_receiving_binding_changed"
            )
            return result
        if manual is not None and (
            device.revision != manual.expected_device_revision
            or realm.revision != manual.expected_realm_revision
            or destination.revision != manual.expected_destination_revision
        ):
            raise ConflictException(
                message="SMS review inputs changed.",
                message_code="sms_review_revision_conflict",
                unique_dict={},
            )
        alias = await self.aliases.get(event.receiving_alias_id)
        if alias.realm_id != realm.id:
            result = await self._decision(
                event, now, "manual", "sms_receiving_binding_changed"
            )
            return result
        if event.origin_reason_code is not None:
            result = await self._decision(
                event, now, "manual", event.origin_reason_code
            )
            return result
        sender_allowed = await asyncio.to_thread(
            _sender_allowed,
            event.original_sender or event.sender,
            event.sender,
            device.senders_json,
        )
        if not sender_allowed:
            result = await self._decision(
                event, now, "manual", "sms_sender_policy_changed"
            )
            return result
        if (
            device.parser_profile_id is None
            or event.parser_revision_id is None
        ):
            result = await self._decision(
                event, now, "manual", "sms_parser_binding_missing"
            )
            return result
        profile = await self.profiles.locked(device.parser_profile_id)
        revision = await self.revisions.get(profile.id, profile.revision)
        if not profile.is_active or revision.id != event.parser_revision_id:
            result = await self._decision(
                event, now, "manual", "sms_parser_binding_changed"
            )
            return result
        if (
            event.direction != "credit"
            or event.parse_reason_code is not None
            or event.amount_rial is None
        ):
            result = await self._decision(
                event,
                now,
                "manual",
                event.parse_reason_code or "sms_not_credit",
            )
            return result
        if not now - window <= financial_at <= now:
            result = await self._decision(
                event, now, "outside_window", "sms_outside_window"
            )
            return result
        origin_required = (
            realm.origin_requirement_since_ms is not None
            or device.settlement_identity_mode == "trusted_origin_fingerprint"
        )
        if origin_required:
            if (
                event.canonicalization_revision != 1
                or event.origin_kind != "direct_sms"
                or event.original_provider_timestamp_ms is None
                or event.origin_identity_sha256 is None
                or (event.declared_notification_sha256 is None)
                or (event.origin_reason_code is not None)
            ):
                result = await self._decision(
                    event,
                    now,
                    "manual",
                    event.origin_reason_code
                    or "sms_original_metadata_missing",
                )
                return result
            if (
                realm.origin_requirement_since_ms is not None
                and event.original_provider_timestamp_ms
                < realm.origin_requirement_since_ms
            ):
                result = await self._decision(
                    event, now, "manual", "sms_origin_before_activation"
                )
                return result
            origin_at = datetime(1970, 1, 1) + timedelta(
                milliseconds=event.original_provider_timestamp_ms
            )
            if origin_at > now + timedelta(
                seconds=capacity.original_timestamp_future_seconds
            ) or origin_at < now - timedelta(
                seconds=capacity.original_timestamp_max_age_seconds
            ):
                result = await self._decision(
                    event, now, "manual", "sms_original_timestamp_policy"
                )
                return result
        if event.bank_reference is None and (
            device.settlement_identity_mode != "trusted_origin_fingerprint"
            or not realm.origin_mode_enabled
        ):
            result = await self._decision(
                event, now, "manual", "sms_bank_reference_required"
            )
            return result
        candidates = await self.reader.candidates(
            event.amount_rial,
            financial_at - window,
            financial_at + grace,
            windows,
            capacity.max_match_candidates + 1,
        )
        if len(candidates) > capacity.max_match_candidates:
            result = await self._decision(
                event, now, "manual", "sms_candidate_capacity"
            )
            return result
        owners = {item.customer_id for item in hints}
        if any((item.customer_id not in owners for item in candidates)):
            result = await self._decision(
                event, now, "waiting", "sms_candidate_owners_changed"
            )
            return result
        legacy = tuple(
            (
                (item.id, item.encrypted_instruction)
                for item in candidates
                if item.receiving_realm_id is None
            )
        )
        associations = await asyncio.to_thread(
            legacy_associations,
            legacy,
            alias.kind,
            alias.account_sha256,
            alias.bank_namespace,
            self.settings.configuration_encryption_key,
        )
        relevant = [
            item
            for item in candidates
            if item.receiving_realm_id == realm.id
            or (
                item.receiving_realm_id is None
                and associations[item.id] is not False
            )
        ]
        if any(
            item.status == "approved" and item.settlement_id is None
            for item in relevant
        ) and (
            manual is None
            or not any(
                item.id == manual.topup_id and item.status == "approved"
                for item in relevant
            )
        ):
            result = await self._decision(
                event, now, "manual", "sms_unlinked_settled_payment"
            )
            return result
        pending = [
            item
            for item in relevant
            if (
                item.status == "pending"
                or manual is not None
                and item.status == "approved"
            )
            and (manual is None or item.id == manual.topup_id)
            and (
                item.receiving_realm_id == realm.id
                or associations.get(item.id) is True
            )
        ]
        if len(pending) != 1:
            result = await self._decision(
                event,
                now,
                "ambiguous" if len(pending) > 1 else "waiting",
                "sms_topup_ambiguous"
                if len(pending) > 1
                else "sms_topup_missing",
                count=len(pending),
            )
            return result
        topup = pending[0]
        if expected_topup_id is not None and topup.id != expected_topup_id:
            result = await self._decision(
                event, now, "waiting", "sms_topup_selection_changed"
            )
            return result
        keys = await asyncio.to_thread(
            _identity_keys,
            event.bank_reference,
            event.origin_identity_sha256,
            event.declared_notification_sha256,
        )
        existing = await self.claims.current_many(keys)
        if existing:
            result = await self._decision(
                event, now, "manual", "sms_settlement_identity_used"
            )
            return result
        # All chosen owners, receiving facts, candidates and identities are now
        # locked. A time observed before those waits cannot authorize credit.
        now = await self.reader.utc_now()
        if device.expires_at <= now:
            result = await self._decision(
                event, now, "manual", "sms_receiving_binding_changed"
            )
            return result
        if not now - window <= financial_at <= now:
            result = await self._decision(
                event, now, "outside_window", "sms_outside_window"
            )
            return result
        if origin_required and (
            financial_at
            > now
            + timedelta(seconds=capacity.original_timestamp_future_seconds)
            or financial_at
            < now
            - timedelta(seconds=capacity.original_timestamp_max_age_seconds)
        ):
            result = await self._decision(
                event, now, "manual", "sms_original_timestamp_policy"
            )
            return result
        proof = SmsSettlementProof(
            event.id,
            device.id,
            realm.id,
            event.parser_revision_id,
            "bank_reference"
            if event.bank_reference is not None
            else "trusted_sms_origin",
            event.bank_reference,
            event.origin_identity_sha256,
            event.declared_notification_sha256,
            event.amount_rial,
            event.original_provider_timestamp_ms,
            1 if event.canonicalization_revision == 1 else None,
        )
        if topup.status == "approved":
            if (
                event.bank_reference is not None
                and topup.bank_reference != event.bank_reference
            ):
                raise ConflictException(
                    message="SMS reference differs from settled payment.",
                    message_code="sms_settled_reference_changed",
                    unique_dict={},
                )
        else:
            await self.wallets.approve_from_sms_proof(topup.id, proof)
        settlement = await self.settlements.create(
            SmsSettlementModel(
                topup_id=topup.id,
                sms_event_id=event.id,
                device_id=device.id,
                receiving_realm_id=realm.id,
                parser_revision_id=event.parser_revision_id,
                evidence_kind=proof.evidence_kind,
                created_by_staff_id=staff_id,
                review_reason=manual.reason if manual is not None else None,
            )
        )
        await self.claims.create_many(settlement.id, keys)
        result = await self._decision(
            event, now, "approved", None, topup.id, settlement.id, len(pending)
        )
        return result

    async def _decision(
        self,
        event: SmsEventModel,
        now: datetime,
        status: str,
        reason: str | None,
        topup_id: int | None = None,
        settlement_id: int | None = None,
        count: int = 0,
    ) -> str:
        await self.decisions.record(
            SmsSettlementDecisionModel(
                sms_event_id=event.id,
                status=status,
                reason_code=reason,
                checked_at=now,
                candidate_count=count,
                topup_id=topup_id,
                settlement_id=settlement_id,
            )
        )
        return status


def _identity_keys(
    bank_reference: str | None,
    origin_identity_sha256: str | None,
    declared_notification_sha256: str | None,
) -> list[tuple[str, str]]:
    keys = []
    if bank_reference is not None:
        keys.append(
            (
                "bank_reference",
                hashlib.sha256(bank_reference.encode()).hexdigest(),
            )
        )
    if origin_identity_sha256 is not None:
        keys.append(("trusted_sms_origin", origin_identity_sha256))
    if declared_notification_sha256 is not None:
        keys.append(("declared_notification", declared_notification_sha256))
    return keys


def _sender_allowed(original: str, transport: str, senders_json: str) -> bool:
    try:
        canonical = normalize_origin_sender(original)
        return canonical == normalize_origin_sender(
            transport
        ) and canonical in {
            normalize_origin_sender(sender)
            for sender in json.loads(senders_json)
        }
    except (ValueError, TypeError):
        return False
