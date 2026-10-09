import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from papilio.errors.exceptions import ConflictException, NotFoundException

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.billing.sms_origins.domain.contracts import (
    SmsOriginCapacity,
    SmsOriginSearch,
)
from src.modules.billing.sms_origins.domain.models import (
    ReceivingRealmModel,
    SmsParserProfileModel,
    SmsParserRevisionModel,
)
from src.modules.billing.sms_origins.infra.mysql import (
    ReceivingRealmRepository,
    SmsOriginAdmissionRepository,
    SmsParserProfileRepository,
    SmsParserRevisionRepository,
)


def sms_conflict(code: str) -> ConflictException:
    return ConflictException(
        message="SMS policy cannot be accepted.",
        message_code=code,
        unique_dict={},
    )


def sms_not_found(code: str) -> NotFoundException:
    return NotFoundException(
        message="SMS record was not found.",
        message_code=code,
        entity="sms_origin",
        identifier="record",
        identifier_value=code,
    )


def capacity(settings: PapilioSettings) -> SmsOriginCapacity:
    if settings.sms_origins is None or not settings.sms_origins.enabled:
        raise sms_conflict("sms_origins_unavailable")
    return settings.sms_origins


def paging(settings: PapilioSettings, data: SmsOriginSearch) -> int:
    configured = settings.sms_origins
    if configured is None:
        return page_size(settings, data.per_page)
    return min(data.per_page or configured.page_size, configured.max_page_size)


class SmsParserProfileService:
    def __init__(
        self, repo: SmsParserProfileRepository, settings: PapilioSettings
    ) -> None:
        self.repo, self.settings = repo, settings

    async def get(self, id: int) -> SmsParserProfileModel:
        row = await self.repo.get_by_id(id)
        if row is None:
            raise sms_not_found("sms_parser_profile_not_found")
        return row

    async def locked(self, id: int) -> SmsParserProfileModel:
        row = await self.repo.locked(id)
        if row is None:
            raise sms_not_found("sms_parser_profile_not_found")
        return row

    async def create(
        self, title: str, is_active: bool
    ) -> SmsParserProfileModel:
        maximum = capacity(self.settings).max_profiles
        ids = await self.repo.admission_ids(maximum)
        if len(ids) >= maximum:
            raise sms_conflict("sms_parser_profile_capacity")
        row = await self.repo.create(
            SmsParserProfileModel(title=title, is_active=is_active)
        )
        return row

    async def update(
        self, row: SmsParserProfileModel, title: str, is_active: bool
    ) -> SmsParserProfileModel:
        result = await self.repo.change(
            row,
            SmsParserProfileModel.patch(
                title=title, is_active=is_active, revision=row.revision + 1
            ),
        )
        return result

    async def search(
        self, data: SmsOriginSearch
    ) -> ServicePage[SmsParserProfileModel]:
        limit = paging(self.settings, data)
        rows = await self.repo.page(data.q, (data.page - 1) * limit, limit)
        return service_page(rows, limit)


class SmsParserRevisionService:
    def __init__(
        self, repo: SmsParserRevisionRepository, settings: PapilioSettings
    ) -> None:
        self.repo, self.settings = repo, settings

    async def get(
        self, profile_id: int, revision: int
    ) -> SmsParserRevisionModel:
        row = await self.repo.current(profile_id, revision)
        if row is None:
            raise sms_not_found("sms_parser_revision_not_found")
        return row

    async def create(
        self, row: SmsParserRevisionModel
    ) -> SmsParserRevisionModel:
        result = await self.repo.create(row)
        return result

    async def history(
        self, profile_id: int, data: SmsOriginSearch
    ) -> ServicePage[SmsParserRevisionModel]:
        limit = paging(self.settings, data)
        rows = await self.repo.page(profile_id, (data.page - 1) * limit, limit)
        return service_page(rows, limit)


class ReceivingRealmService:
    def __init__(
        self, repo: ReceivingRealmRepository, settings: PapilioSettings
    ) -> None:
        self.repo, self.settings = repo, settings

    async def get(self, id: int) -> ReceivingRealmModel:
        row = await self.repo.get_by_id(id)
        if row is None:
            raise sms_not_found("sms_receiving_realm_not_found")
        return row

    async def locked(self, id: int) -> ReceivingRealmModel:
        row = await self.repo.locked(id)
        if row is None:
            raise sms_not_found("sms_receiving_realm_not_found")
        return row

    async def create(
        self, title: str, active: bool, origin_enabled: bool
    ) -> ReceivingRealmModel:
        maximum = capacity(self.settings).max_realms
        ids = await self.repo.admission_ids(maximum)
        if len(ids) >= maximum:
            raise sms_conflict("sms_receiving_realm_capacity")
        key = await asyncio.to_thread(uuid4)
        # Captured at first activation, never reinterpret historical events.
        now = await self.repo.utc_now()
        since = _database_ms(now) if origin_enabled else None
        row = await self.repo.create(
            ReceivingRealmModel(
                realm_key=str(key),
                title=title,
                is_active=active,
                origin_mode_enabled=origin_enabled,
                origin_requirement_since_ms=since,
            )
        )
        return row

    async def update(
        self,
        row: ReceivingRealmModel,
        title: str,
        active: bool,
        origin_enabled: bool,
    ) -> ReceivingRealmModel:
        since = row.origin_requirement_since_ms
        if origin_enabled and since is None:
            now = await self.repo.utc_now()
            since = _database_ms(now)
        result = await self.repo.change(
            row,
            ReceivingRealmModel.patch(
                title=title,
                is_active=active,
                origin_mode_enabled=origin_enabled,
                origin_requirement_since_ms=since,
                revision=row.revision + 1,
            ),
        )
        return result

    async def search(
        self, data: SmsOriginSearch
    ) -> ServicePage[ReceivingRealmModel]:
        limit = paging(self.settings, data)
        rows = await self.repo.page(data.q, (data.page - 1) * limit, limit)
        return service_page(rows, limit)


class SmsOriginAdmissionService:
    def __init__(self, repo: SmsOriginAdmissionRepository) -> None:
        self.repo = repo

    async def acquire(self) -> None:
        row = await self.repo.locked("policy_creation")
        if row is None:
            raise sms_conflict("sms_origin_admission_unavailable")

    async def settlement_guard(self) -> None:
        row = await self.repo.locked("settlement_identity")
        if row is None:
            raise sms_conflict("sms_settlement_admission_unavailable")


def _database_ms(value: datetime) -> int:
    instant = (
        value.replace(tzinfo=UTC)
        if value.tzinfo is None
        else value.astimezone(UTC)
    )
    delta = instant - datetime(1970, 1, 1, tzinfo=UTC)
    return (
        delta.days * 86400000
        + delta.seconds * 1000
        + delta.microseconds // 1000
    )
