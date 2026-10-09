import asyncio
from datetime import UTC

from src.config.pagination import ServicePage
from src.config.settings import PapilioSettings
from src.modules.billing.sms_origins.app.commands import revision_output
from src.modules.billing.sms_origins.app.services import paging, sms_not_found
from src.modules.billing.sms_origins.domain.contracts import (
    ParserProfileRead,
    ParserRevisionRead,
    ReceivingRealmRead,
    SmsOriginSearch,
)
from src.modules.billing.sms_origins.domain.facts import ParserProfileFacts
from src.modules.billing.sms_origins.infra.readers import (
    SmsParserProfileReader,
)
from src.modules.billing.sms_origins.interfaces import (
    IReceivingRealmService,
    ISmsParserRevisionService,
)


def profile_output(row: ParserProfileFacts) -> ParserProfileRead:
    return ParserProfileRead(
        id=row.id,
        title=row.title,
        is_active=row.is_active,
        revision=row.revision,
        current_parser_revision_id=row.current_parser_revision_id,
        created_at=row.created_at.replace(tzinfo=UTC),
    )


class SmsOriginQuery:
    def __init__(
        self,
        profiles: SmsParserProfileReader,
        revisions: ISmsParserRevisionService,
        realms: IReceivingRealmService,
        settings: PapilioSettings,
    ) -> None:
        self.profiles, self.revisions, self.realms, self.settings = (
            profiles,
            revisions,
            realms,
            settings,
        )

    async def profile(self, id: int) -> ParserProfileRead:
        row = await self.profiles.get(id)
        if row is None:
            raise sms_not_found("sms_parser_profile_not_found")
        return profile_output(row)

    async def profiles_page(
        self, data: SmsOriginSearch
    ) -> ServicePage[ParserProfileRead]:
        limit = paging(self.settings, data)
        rows = await self.profiles.page(data.q, (data.page - 1) * limit, limit)
        return ServicePage(
            items=[profile_output(row) for row in rows.items],
            total_items=rows.total_items,
            per_page=limit,
        )

    async def revision(self, id: int, revision: int) -> ParserRevisionRead:
        row = await self.revisions.get(id, revision)
        assert row.created_at is not None
        result = await asyncio.to_thread(
            revision_output,
            row.id,
            row.profile_id,
            row.revision,
            row.definition_json,
            row.definition_sha256,
            row.created_by_staff_id,
            row.created_at,
        )
        return result

    async def revisions_page(
        self, id: int, data: SmsOriginSearch
    ) -> ServicePage[ParserRevisionRead]:
        parent = await self.profiles.get(id)
        if parent is None:
            raise sms_not_found("sms_parser_profile_not_found")
        rows = await self.revisions.history(id, data)
        snapshots = tuple(
            (
                row.id,
                row.profile_id,
                row.revision,
                row.definition_json,
                row.definition_sha256,
                row.created_by_staff_id,
                row.created_at,
            )
            for row in rows.items
        )
        items = await asyncio.to_thread(
            lambda values: [revision_output(*value) for value in values],
            snapshots,
        )
        return ServicePage(
            items=items, total_items=rows.total_items, per_page=rows.per_page
        )

    async def realm(self, id: int) -> ReceivingRealmRead:
        row = await self.realms.get(id)
        result = ReceivingRealmRead.model_validate(row, from_attributes=True)
        return result.model_copy(
            update={"created_at": result.created_at.replace(tzinfo=UTC)}
        )

    async def realms_page(
        self, data: SmsOriginSearch
    ) -> ServicePage[ReceivingRealmRead]:
        rows = await self.realms.search(data)
        items = [
            ReceivingRealmRead.model_validate(row, from_attributes=True)
            for row in rows.items
        ]
        return ServicePage(
            items=[
                row.model_copy(
                    update={"created_at": row.created_at.replace(tzinfo=UTC)}
                )
                for row in items
            ],
            total_items=rows.total_items,
            per_page=rows.per_page,
        )
