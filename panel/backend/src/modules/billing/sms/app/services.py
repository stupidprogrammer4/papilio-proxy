import asyncio
import json
from datetime import UTC
from uuid import UUID

from papilio.errors.exceptions import ConflictException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import hash_sha256

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.billing.sms.app.parser import observe, observe_strict
from src.modules.billing.sms.domain.dtos import SmsReceived, SmsSearch
from src.modules.billing.sms.domain.models import SmsEventModel
from src.modules.billing.sms.infra.mysql import SmsRepository
from src.modules.billing.sms_origins.app.parsing import (
    ParserInput,
    declared_notification_digest,
    message_digest,
    normalize_origin_sender,
    origin_digest,
    parse,
)
from src.modules.billing.sms_origins.app.services import sms_not_found
from src.modules.billing.sms_origins.domain.contracts import (
    OriginFingerprintInput,
)
from src.modules.billing.sms_origins.interfaces import ISmsOriginIntakeQuery


class SmsService:
    def __init__(
        self,
        repo: SmsRepository,
        settings: PapilioSettings,
        origins: ISmsOriginIntakeQuery,
    ) -> None:
        self.repo = repo
        self.settings = settings
        self.origins = origins

    @handle_conflicts
    @transactional
    async def receive(
        self, data: SmsReceived, *, device_id: int | None = None
    ) -> SmsEventModel:
        digest = await asyncio.to_thread(hash_sha256, data.message)
        sent_at = data.sent_at.astimezone(UTC).replace(
            tzinfo=None, microsecond=0
        )
        existing = await self.repo.by_event_id(data.event_id)
        if existing is not None:
            if (
                existing.device_id != device_id
                or existing.sender != data.sender
                or existing.text_digest != digest
                or existing.sent_at != sent_at
                or existing.original_provider_timestamp_ms
                != (
                    data.origin.original_provider_timestamp_ms
                    if data.origin
                    else None
                )
                or existing.original_sender
                != (data.origin.original_sender if data.origin else None)
                or existing.origin_kind
                != (data.origin.kind if data.origin else None)
                or existing.canonicalization_revision
                != (
                    data.origin.canonicalization_revision
                    if data.origin
                    else None
                )
            ):
                raise ConflictException(
                    message="شناسهٔ پیامک برای متن دیگری ثبت شده است.",
                    message_code="sms_event_reused",
                    unique_dict={"event_id": data.event_id},
                )
            return existing
        amount, reference = await asyncio.to_thread(
            observe_strict if device_id is not None else observe, data.message
        )
        facts = (
            await self.origins.get(device_id)
            if device_id is not None
            else None
        )
        configured = self.settings.sms_origins
        direction, balance, reason = None, None, None
        if (
            facts is not None
            and facts.parser_definition_json is not None
            and facts.parser_revision_id is not None
            and facts.parser_definition_sha256 is not None
        ):
            if configured is None or not configured.enabled:
                amount, reference, reason = (
                    None,
                    None,
                    "sms_origins_unavailable",
                )
            else:
                observed = await asyncio.to_thread(
                    parse,
                    ParserInput(
                        data.message,
                        facts.parser_definition_json,
                        facts.parser_revision_id,
                        facts.parser_definition_sha256,
                        configured.max_message_bytes,
                        configured.max_clauses,
                    ),
                )
                amount, reference, balance, direction, reason = (
                    observed.deposit_rial,
                    observed.bank_reference,
                    observed.balance_rial,
                    observed.direction,
                    observed.reason_code,
                )
        canonical = (
            await asyncio.to_thread(message_digest, data.message)
            if facts is not None
            else None
        )
        origin_key = None
        notification_key = None
        origin_reason = None
        if (
            data.origin is not None
            and facts is not None
            and facts.realm_key is not None
            and canonical is not None
        ):
            declared = await asyncio.to_thread(
                _declared_sender_allowed,
                data.origin.original_sender,
                data.sender,
                facts.enrolled_senders_json,
            )
            if not declared:
                origin_reason = "sms_original_sender_untrusted"
            if declared:
                origin_key = await asyncio.to_thread(
                    origin_digest,
                    OriginFingerprintInput(
                        UUID(facts.realm_key),
                        data.origin.original_sender,
                        data.origin.original_provider_timestamp_ms,
                        canonical,
                        data.origin.canonicalization_revision,
                    ),
                )
        if (
            origin_key is not None
            and data.origin is not None
            and facts is not None
            and facts.realm_key is not None
            and canonical is not None
        ):
            notification_key = await asyncio.to_thread(
                declared_notification_digest,
                OriginFingerprintInput(
                    UUID(facts.realm_key),
                    data.origin.original_sender,
                    data.origin.original_provider_timestamp_ms,
                    canonical,
                    data.origin.canonicalization_revision,
                ),
            )
        result = await self.repo.create(
            SmsEventModel(
                parser_revision_id=facts.parser_revision_id if facts else None,
                parser_definition_sha256=facts.parser_definition_sha256
                if facts
                else None,
                receiving_realm_id=facts.realm_id if facts else None,
                receiving_alias_id=facts.alias_id if facts else None,
                captured_destination_id=facts.destination_id
                if facts
                else None,
                captured_destination_revision=facts.destination_revision
                if facts
                else None,
                direction=direction,
                balance_rial=balance,
                parse_reason_code=reason,
                canonical_message_digest=canonical,
                origin_identity_sha256=origin_key,
                declared_notification_sha256=notification_key,
                origin_reason_code=origin_reason,
                original_provider_timestamp_ms=data.origin.original_provider_timestamp_ms
                if data.origin
                else None,
                original_sender=data.origin.original_sender
                if data.origin
                else None,
                origin_kind=data.origin.kind if data.origin else None,
                canonicalization_revision=data.origin.canonicalization_revision
                if data.origin
                else None,
                device_id=device_id,
                event_id=data.event_id,
                sender=data.sender,
                text_digest=digest,
                amount_rial=amount,
                bank_reference=reference,
                sent_at=sent_at,
            )
        )
        return result

    async def get(self, id: int) -> SmsEventModel:
        row = await self.repo.get_by_id(id)
        if row is None:
            raise sms_not_found("sms_event_not_found")
        return row

    async def search(self, data: SmsSearch) -> ServicePage[SmsEventModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page((data.page - 1) * limit, limit)
        return service_page(result, limit)


def _declared_sender_allowed(
    original: str, transport: str, senders_json: str
) -> bool:
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
