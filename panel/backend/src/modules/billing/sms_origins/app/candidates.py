import asyncio
from datetime import UTC, datetime, timedelta
from typing import Literal

from src.config.pagination import ServicePage
from src.config.settings import PapilioSettings
from src.modules.billing.sms.infra.mysql import SmsRepository
from src.modules.billing.sms_origins.app.association import legacy_associations
from src.modules.billing.sms_origins.app.services import (
    paging,
    sms_conflict,
    sms_not_found,
)
from src.modules.billing.sms_origins.domain.contracts import (
    SmsOriginSearch,
    SmsSettlementCandidateRead,
)
from src.modules.billing.sms_origins.infra.financial import SmsFinancialReader
from src.modules.billing.sms_origins.interfaces import IReceivingAliasService


class SmsSettlementCandidateQuery:
    """Read the bounded matching set before applying page offsets."""

    def __init__(
        self,
        reader: SmsFinancialReader,
        messages: SmsRepository,
        aliases: IReceivingAliasService,
        settings: PapilioSettings,
    ) -> None:
        self.reader, self.messages, self.aliases = reader, messages, aliases
        self.settings = settings

    async def get(
        self, id: int, data: SmsOriginSearch
    ) -> ServicePage[SmsSettlementCandidateRead]:
        event = await self.messages.get_by_id(id)
        if event is None:
            raise sms_not_found("sms_not_found")
        capacity = self.settings.sms_origins
        if capacity is None:
            raise sms_conflict("sms_origins_unavailable")
        limit = paging(self.settings, data)
        if (
            event.amount_rial is None
            or event.receiving_alias_id is None
            or event.receiving_realm_id is None
        ):
            return ServicePage((), 0, limit)
        at = (
            datetime(1970, 1, 1)
            + timedelta(milliseconds=event.original_provider_timestamp_ms)
            if event.original_provider_timestamp_ms is not None
            and event.origin_kind == "direct_sms"
            else event.sent_at
        )
        windows: list[
            tuple[list[str], Literal["created_at", "updated_at"]]
        ] = [(["pending"], "created_at"), (["approved"], "updated_at")]
        facts = await self.reader.candidate_facts(
            event.amount_rial,
            at
            - timedelta(hours=self.settings.operations.sms_match_window_hours),
            at
            + timedelta(
                minutes=self.settings.operations.sms_match_before_topup_minutes
            ),
            windows,
            capacity.max_match_candidates + 1,
        )
        if len(facts) > capacity.max_match_candidates:
            raise sms_conflict("sms_candidate_capacity")
        alias = await self.aliases.get(event.receiving_alias_id)
        legacy = tuple(
            (item.id, item.encrypted_instruction)
            for item in facts
            if item.receiving_realm_id is None
        )
        associations = await asyncio.to_thread(
            legacy_associations,
            legacy,
            alias.kind,
            alias.account_sha256,
            alias.bank_namespace,
            self.settings.configuration_encryption_key,
        )
        items = tuple(
            SmsSettlementCandidateRead.model_validate(
                {
                    "topup_id": item.id,
                    "customer_id": item.customer_id,
                    "amount_rial": item.amount_rial,
                    "status": item.status,
                    "destination_id": item.destination_id,
                    "captured_receiving_realm_id": item.receiving_realm_id,
                    "association_kind": "captured_realm"
                    if item.receiving_realm_id is not None
                    else "immutable_instruction"
                    if associations[item.id] is True
                    else "unresolved",
                    "created_at": item.created_at.replace(tzinfo=UTC),
                    "updated_at": item.updated_at.replace(tzinfo=UTC),
                    "already_linked": item.settlement_id is not None,
                    "selectable": capacity.enabled
                    and item.settlement_id is None
                    and (
                        item.receiving_realm_id == event.receiving_realm_id
                        or associations.get(item.id) is True
                    ),
                }
            )
            for item in facts
            if item.receiving_realm_id == event.receiving_realm_id
            or item.receiving_realm_id is None
            and associations[item.id] is not False
        )
        offset = (data.page - 1) * limit
        return ServicePage(items[offset : offset + limit], len(items), limit)
