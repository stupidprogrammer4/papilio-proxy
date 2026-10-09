import asyncio
import hashlib
import hmac
import json
import secrets
import time
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from papilio.errors.exceptions import ConflictException, NotFoundException
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import decrypt, encrypt, secure_compare

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.billing.destinations.interfaces import (
    IPaymentDestinationService,
)
from src.modules.billing.sms.domain.dtos import SmsReceived
from src.modules.billing.sms_devices.domain.dtos import (
    SmsDeviceSearch,
    SmsDeviceWrite,
)
from src.modules.billing.sms_devices.domain.models import SmsDeviceModel
from src.modules.billing.sms_devices.domain.results import (
    SmsDeviceEnrollment,
    SmsDeviceRead,
)
from src.modules.billing.sms_devices.infra.mysql import SmsDeviceRepository
from src.modules.billing.sms_origins.app.services import capacity, sms_conflict
from src.modules.billing.sms_origins.interfaces import (
    IReceivingAliasService,
    IReceivingRealmService,
    ISmsParserProfileService,
)


class SmsDeviceService:
    def __init__(
        self,
        repo: SmsDeviceRepository,
        settings: PapilioSettings,
        destinations: IPaymentDestinationService,
        profiles: ISmsParserProfileService,
        aliases: IReceivingAliasService,
        realms: IReceivingRealmService,
    ) -> None:
        self.repo, self.settings = repo, settings
        self.destinations = destinations
        self.profiles, self.aliases, self.realms = profiles, aliases, realms

    @staticmethod
    def read(row: SmsDeviceModel) -> SmsDeviceRead:
        return SmsDeviceRead(
            parser_profile_id=row.parser_profile_id,
            settlement_identity_mode=row.settlement_identity_mode,
            approval_mode=row.approval_mode,
            destination_id=row.destination_id,
            id=row.id,
            label=row.label,
            senders=json.loads(row.senders_json),
            is_active=row.is_active,
            revision=row.revision,
            expires_at=row.expires_at.replace(tzinfo=UTC),
        )

    async def get(self, id: int) -> SmsDeviceRead:
        row = await self.repo.get_by_id(id)
        if row is None:
            raise NotFoundException(
                message="SMS device not found",
                message_code="sms_device_not_found",
                entity="sms_device",
                identifier="id",
                identifier_value=id,
            )
        return self.read(row)

    async def origin_policy(
        self,
        profile: int | None,
        identity: str,
        destination_id: int | None,
        approval_mode: str,
        active: bool,
    ) -> None:
        if not active:
            return
        if profile is not None:
            capacity(self.settings)
            row = await self.profiles.get(profile)
            if not row.is_active:
                raise sms_conflict("sms_parser_profile_inactive")
        if identity == "trusted_origin_fingerprint":
            capacity(self.settings)
            if (
                profile is None
                or destination_id is None
                or approval_mode != "unique_sms"
            ):
                raise sms_conflict("sms_origin_device_prerequisites")
            destination = await self.destinations.get(destination_id)
            if destination.receiving_alias_id is None:
                raise sms_conflict("sms_receiving_account_required")
            alias = await self.aliases.get(destination.receiving_alias_id)
            realm = await self.realms.get(alias.realm_id)
            if (
                not realm.is_active
                or not realm.origin_mode_enabled
                or realm.origin_requirement_since_ms is None
            ):
                raise sms_conflict("sms_origin_realm_required")

    def validity(
        self, data: SmsDeviceWrite, *, allow_revocation: bool = False
    ) -> datetime:
        policy = self.settings.sms_devices
        expiry = data.expires_at.astimezone(UTC).replace(tzinfo=None)
        if policy is None or not policy.enabled:
            if allow_revocation and not data.is_active:
                return expiry
            raise ConflictException(
                message="SMS devices are disabled",
                message_code="sms_devices_disabled",
                unique_dict={},
            )
        if len(data.senders) > policy.max_senders_per_device:
            raise ConflictException(
                message="Sender capacity exceeded",
                message_code="sms_device_sender_capacity",
                unique_dict={},
            )
        if data.is_active and expiry <= datetime.now(UTC).replace(tzinfo=None):
            raise ConflictException(
                message="An active device must expire in the future",
                message_code="sms_device_expired",
                unique_dict={},
            )
        if expiry > datetime.now(UTC).replace(tzinfo=None) + timedelta(
            days=policy.max_key_validity_days
        ):
            raise ConflictException(
                message="Key expiry exceeds owning capacity",
                message_code="sms_device_expiry_capacity",
                unique_dict={},
            )
        return expiry

    @transactional
    async def create(self, data: SmsDeviceWrite) -> SmsDeviceEnrollment:
        await self.origin_policy(
            data.parser_profile_id,
            data.settlement_identity_mode,
            data.destination_id,
            data.approval_mode,
            data.is_active,
        )
        if data.destination_id is not None:
            await self.destinations.get(data.destination_id)
        key = secrets.token_urlsafe(32)
        ciphertext = await asyncio.to_thread(
            encrypt, key, self.settings.configuration_encryption_key
        )
        row = await self.repo.create(
            SmsDeviceModel(
                parser_profile_id=data.parser_profile_id,
                settlement_identity_mode=data.settlement_identity_mode,
                approval_mode=data.approval_mode,
                destination_id=data.destination_id,
                label=data.label,
                encrypted_key=ciphertext,
                senders_json=json.dumps(data.senders),
                expires_at=self.validity(data),
                is_active=data.is_active,
            )
        )
        return SmsDeviceEnrollment(device=self.read(row), api_key=key)

    @transactional
    async def update(self, id: int, data: SmsDeviceWrite) -> SmsDeviceRead:
        row = await self.repo.locked(id)
        self.revision(row, id, data.expected_revision)
        assert row is not None
        profile = (
            data.parser_profile_id
            if "parser_profile_id" in data.model_fields_set
            else row.parser_profile_id
        )
        identity = (
            data.settlement_identity_mode
            if "settlement_identity_mode" in data.model_fields_set
            else row.settlement_identity_mode
        )
        await self.origin_policy(
            profile,
            identity,
            data.destination_id,
            data.approval_mode,
            data.is_active,
        )
        if data.destination_id is not None:
            await self.destinations.get(data.destination_id)
        result = await self.repo.change(
            row,
            SmsDeviceModel.patch(
                parser_profile_id=profile,
                settlement_identity_mode=identity,
                approval_mode=data.approval_mode,
                destination_id=data.destination_id,
                label=data.label,
                senders_json=json.dumps(data.senders),
                expires_at=self.validity(data, allow_revocation=True),
                is_active=data.is_active,
                revision=row.revision + 1,
            ),
        )
        return self.read(result)

    @transactional
    async def rotate(
        self, id: int, expected_revision: int
    ) -> SmsDeviceEnrollment:
        row = await self.repo.locked(id)
        self.revision(row, id, expected_revision)
        assert row is not None
        key = secrets.token_urlsafe(32)
        ciphertext = await asyncio.to_thread(
            encrypt, key, self.settings.configuration_encryption_key
        )
        result = await self.repo.change(
            row,
            SmsDeviceModel.patch(
                encrypted_key=ciphertext, revision=row.revision + 1
            ),
        )
        return SmsDeviceEnrollment(device=self.read(result), api_key=key)

    @staticmethod
    def revision(
        row: SmsDeviceModel | None, id: int, expected: int | None
    ) -> None:
        if row is None:
            raise NotFoundException(
                message="SMS device not found",
                message_code="sms_device_not_found",
                entity="sms_device",
                identifier="id",
                identifier_value=id,
            )
        if expected != row.revision:
            raise ConflictException(
                message="Refresh the changed device before saving",
                message_code="sms_device_revision_conflict",
                unique_dict={"id": id},
            )

    async def search(
        self, data: SmsDeviceSearch
    ) -> ServicePage[SmsDeviceRead]:
        limit = page_size(self.settings, data.per_page)
        rows = await self.repo.page((data.page - 1) * limit, limit, data.q)
        result = service_page(rows, limit)
        return ServicePage(
            items=[self.read(row) for row in result.items],
            total_items=result.total_items,
            per_page=limit,
        )

    async def verify(
        self,
        id: int,
        timestamp: str,
        signature: str,
        raw: bytes,
        sms: SmsReceived,
    ) -> None:
        policy = self.settings.sms_devices
        if policy is None or not policy.enabled:
            raise HTTPException(401, "Device intake is disabled")
        row = await self.repo.get_by_id(id)
        now = datetime.now(UTC).replace(tzinfo=None)
        valid_time = (
            timestamp.isascii()
            and timestamp.isdecimal()
            and len(timestamp) <= 20
        )
        if (
            not valid_time
            or abs(time.time() - int(timestamp))
            > self.settings.operations.sms_clock_skew_seconds
        ):
            raise HTTPException(401, "Invalid device authentication")
        if row is None or not row.is_active or row.expires_at <= now:
            raise HTTPException(401, "Invalid device authentication")
        key = await asyncio.to_thread(
            decrypt,
            row.encrypted_key,
            self.settings.configuration_encryption_key,
        )
        mac = await asyncio.to_thread(
            hmac.new,
            key.encode(),
            f"{id}.{timestamp}.".encode() + raw,
            hashlib.sha256,
        )
        if not signature.isascii() or not secure_compare(
            mac.hexdigest(), signature
        ):
            raise HTTPException(401, "Invalid device authentication")
        if sms.sender not in json.loads(row.senders_json):
            raise HTTPException(403, "Sender is not enrolled for this device")
