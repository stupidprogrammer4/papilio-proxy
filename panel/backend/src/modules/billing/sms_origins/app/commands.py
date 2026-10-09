import asyncio
import hashlib
from datetime import UTC, datetime

from papilio.infra.db.tools.decorators import transactional

from src.config.settings import PapilioSettings
from src.modules.billing.sms_origins.app.parsing import (
    ParserInput,
    generated_sample,
    parse,
    validate_definition,
)
from src.modules.billing.sms_origins.app.services import capacity, sms_conflict
from src.modules.billing.sms_origins.domain.contracts import (
    BankSmsParserDefinition,
    GeneratedParserSample,
    ParserPreviewRead,
    ParserProfileCreate,
    ParserProfileRead,
    ParserProfileUpdate,
    ParserRevisionRead,
    ReceivingRealmCreate,
    ReceivingRealmRead,
    ReceivingRealmUpdate,
)
from src.modules.billing.sms_origins.domain.models import (
    SmsParserRevisionModel,
)
from src.modules.billing.sms_origins.interfaces import (
    IReceivingRealmService,
    ISmsOriginAdmissionService,
    ISmsParserProfileService,
    ISmsParserRevisionService,
)


def revision_output(
    id: int,
    profile_id: int,
    revision: int,
    document: str,
    sha256: str,
    actor: int | None,
    created_at: datetime,
) -> ParserRevisionRead:
    return ParserRevisionRead(
        id=id,
        profile_id=profile_id,
        revision=revision,
        definition=BankSmsParserDefinition.model_validate_json(document),
        definition_sha256=sha256,
        created_by_staff_id=actor,
        created_at=created_at.replace(tzinfo=UTC),
    )


class SmsParserCommand:
    def __init__(
        self,
        profiles: ISmsParserProfileService,
        revisions: ISmsParserRevisionService,
        settings: PapilioSettings,
        admission: ISmsOriginAdmissionService,
    ) -> None:
        self.admission = admission
        self.profiles, self.revisions, self.settings = (
            profiles,
            revisions,
            settings,
        )

    @transactional
    async def create(
        self, data: ParserProfileCreate, staff_id: int
    ) -> ParserProfileRead:
        policy = capacity(self.settings).model_copy(deep=True)
        document = await asyncio.to_thread(
            validate_definition, data.definition.model_copy(deep=True), policy
        )
        digest = await asyncio.to_thread(
            lambda value: hashlib.sha256(value.encode()).hexdigest(), document
        )
        await self.admission.acquire()
        row = await self.profiles.create(data.title, data.is_active)
        revision = await self.revisions.create(
            SmsParserRevisionModel(
                profile_id=row.id,
                revision=row.revision,
                definition_json=document,
                definition_sha256=digest,
                created_by_staff_id=staff_id,
            )
        )
        assert row.created_at is not None
        return ParserProfileRead(
            id=row.id,
            title=row.title,
            is_active=row.is_active,
            revision=row.revision,
            current_parser_revision_id=revision.id,
            created_at=row.created_at.replace(tzinfo=UTC),
        )

    @transactional
    async def update(
        self, id: int, data: ParserProfileUpdate, staff_id: int
    ) -> ParserProfileRead:
        policy = capacity(self.settings).model_copy(deep=True)
        document = await asyncio.to_thread(
            validate_definition, data.definition.model_copy(deep=True), policy
        )
        digest = await asyncio.to_thread(
            lambda value: hashlib.sha256(value.encode()).hexdigest(), document
        )
        row = await self.profiles.locked(id)
        if row.revision != data.expected_revision:
            raise sms_conflict("sms_parser_revision_conflict")
        updated = await self.profiles.update(row, data.title, data.is_active)
        revision = await self.revisions.create(
            SmsParserRevisionModel(
                profile_id=updated.id,
                revision=updated.revision,
                definition_json=document,
                definition_sha256=digest,
                created_by_staff_id=staff_id,
            )
        )
        assert updated.created_at is not None
        return ParserProfileRead(
            id=updated.id,
            title=updated.title,
            is_active=updated.is_active,
            revision=updated.revision,
            current_parser_revision_id=revision.id,
            created_at=updated.created_at.replace(tzinfo=UTC),
        )

    async def sample(
        self,
        profile_id: int,
        revision_number: int,
        data: GeneratedParserSample,
    ) -> ParserPreviewRead:
        policy = capacity(self.settings)
        revision = await self.revisions.get(profile_id, revision_number)
        document, id, sha256 = (
            revision.definition_json,
            revision.id,
            revision.definition_sha256,
        )
        definition = await asyncio.to_thread(
            BankSmsParserDefinition.model_validate_json, document
        )
        try:
            message = await asyncio.to_thread(
                generated_sample, definition, data.model_copy(deep=True)
            )
        except ValueError as error:
            raise sms_conflict(str(error)) from error
        observation = await asyncio.to_thread(
            parse,
            ParserInput(
                message,
                document,
                id,
                sha256,
                policy.max_message_bytes,
                policy.max_clauses,
            ),
        )
        return ParserPreviewRead(
            generated_message=message,
            direction=observation.direction,
            deposit_rial=observation.deposit_rial,
            balance_rial=observation.balance_rial,
            bank_reference=observation.bank_reference,
            reason_code=observation.reason_code,
            parser_revision_id=id,
            definition_sha256=sha256,
        )


class ReceivingRealmCommand:
    def __init__(
        self,
        realms: IReceivingRealmService,
        settings: PapilioSettings,
        admission: ISmsOriginAdmissionService,
    ) -> None:
        self.realms, self.settings = realms, settings
        self.admission = admission

    @transactional
    async def create(self, data: ReceivingRealmCreate) -> ReceivingRealmRead:
        capacity(self.settings)
        await self.admission.acquire()
        row = await self.realms.create(
            data.title, data.is_active, data.origin_mode_enabled
        )
        result = ReceivingRealmRead.model_validate(row, from_attributes=True)
        return result.model_copy(
            update={"created_at": result.created_at.replace(tzinfo=UTC)}
        )

    @transactional
    async def update(
        self, id: int, data: ReceivingRealmUpdate
    ) -> ReceivingRealmRead:
        capacity(self.settings)
        row = await self.realms.locked(id)
        if row.revision != data.expected_revision:
            raise sms_conflict("sms_receiving_realm_revision_conflict")
        updated = await self.realms.update(
            row, data.title, data.is_active, data.origin_mode_enabled
        )
        result = ReceivingRealmRead.model_validate(
            updated, from_attributes=True
        )
        return result.model_copy(
            update={"created_at": result.created_at.replace(tzinfo=UTC)}
        )
