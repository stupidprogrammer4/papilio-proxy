import asyncio

from papilio.errors.exceptions import ConflictException, NotFoundException
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import decrypt, encrypt

from src.config.pagination import ServicePage, page_size
from src.config.settings import PapilioSettings
from src.modules.billing.destinations.domain.dtos import (
    DestinationSearch,
    DestinationWrite,
)
from src.modules.billing.destinations.domain.models import (
    PaymentDestinationModel,
)
from src.modules.billing.destinations.domain.results import (
    DestinationDetails,
    PaymentInstruction,
)
from src.modules.billing.destinations.infra.mysql import (
    PaymentDestinationRepository,
)
from src.modules.operations.preferences.interfaces import IPreferencesService


class PaymentDestinationService:
    def __init__(
        self,
        repo: PaymentDestinationRepository,
        settings: PapilioSettings,
        preferences: IPreferencesService,
    ) -> None:
        self.repo = repo
        self.settings = settings
        self.preferences = preferences

    @transactional
    async def create(self, data: DestinationWrite) -> DestinationDetails:
        row = await self.repo.create(
            PaymentDestinationModel(
                title=data.title,
                kind=data.kind,
                encrypted_details=(
                    await asyncio.to_thread(
                        encrypt,
                        data.model_dump_json(),
                        self.settings.configuration_encryption_key,
                    )
                ),
                is_active=data.is_active,
            )
        )
        result = await self._details(row)
        return result

    @transactional
    async def update(
        self, id: int, data: DestinationWrite
    ) -> DestinationDetails:
        row = await self.repo.locked(id)
        if row is None:
            raise _missing(id)
        if (
            data.expected_revision is not None
            and data.expected_revision != row.revision
        ):
            raise ConflictException(
                message="Destination changed.",
                message_code="payment_destination_revision_conflict",
                unique_dict={},
            )
        previous = await self._details(row)
        account_changed = (
            previous.account != data.account or previous.kind != data.kind
        )
        updated = await self.repo.change(
            row,
            PaymentDestinationModel.patch(
                revision=row.revision + 1,
                receiving_alias_id=None
                if account_changed
                else row.receiving_alias_id,
                title=data.title,
                kind=data.kind,
                encrypted_details=(
                    await asyncio.to_thread(
                        encrypt,
                        data.model_dump_json(),
                        self.settings.configuration_encryption_key,
                    )
                ),
                is_active=data.is_active,
            ),
        )
        result = await self._details(updated)
        return result

    async def get(self, id: int) -> DestinationDetails:
        row = await self.repo.get_by_id(id)
        if row is None:
            raise _missing(id)
        result = await self._details(row)
        return result

    async def locked(self, id: int) -> DestinationDetails:
        row = await self.repo.locked(id)
        if row is None:
            raise _missing(id)
        result = await self._details(row)
        return result

    async def assign_receiving_alias(
        self, id: int, expected_revision: int, alias_id: int
    ) -> DestinationDetails:
        row = await self.repo.locked(id)
        if row is None:
            raise _missing(id)
        if row.revision != expected_revision:
            raise ConflictException(
                message="Destination changed.",
                message_code="payment_destination_revision_conflict",
                unique_dict={},
            )
        updated = await self.repo.change(
            row,
            PaymentDestinationModel.patch(
                receiving_alias_id=alias_id, revision=row.revision + 1
            ),
        )
        result = await self._details(updated)
        return result

    async def instruction(self, id: int) -> PaymentInstruction:
        details = await self.instruction_details(id)
        return PaymentInstruction.model_validate(details.model_dump())

    async def instruction_details(self, id: int) -> DestinationDetails:
        row = await self.repo.get_by_id(id)
        if row is None:
            raise _missing(id)
        policy = (
            await self.preferences.current()
        ).values.checkout or self.settings.checkout.policy
        if (
            not row.is_active
            or row.kind not in policy.allowed_methods
            or policy.destination_mode == "legacy"
        ):
            raise ConflictException(
                message="این مقصد پرداخت در دسترس نیست.",
                message_code="payment_destination_unavailable",
                unique_dict={"id": id},
            )
        details = await self._details(row)
        return details

    async def search(
        self, data: DestinationSearch, customer: bool = False
    ) -> ServicePage[DestinationDetails]:
        limit = page_size(self.settings, data.per_page)
        policy = (
            await self.preferences.current()
        ).values.checkout or self.settings.checkout.policy
        kinds: list[str] | None = (
            list(policy.allowed_methods) if customer else None
        )
        if customer and policy.destination_mode == "legacy":
            kinds = []
        result = await self.repo.page(
            data.q,
            True if customer else data.active,
            kinds,
            (data.page - 1) * limit,
            limit,
        )
        snapshots = tuple(
            (
                row.id,
                row.encrypted_details,
                row.receiving_alias_id,
                row.revision,
            )
            for row in result.items
        )
        key = self.settings.configuration_encryption_key
        items = await asyncio.to_thread(_decode_destinations, snapshots, key)
        return ServicePage(
            items=items, total_items=result.total_items, per_page=limit
        )

    async def _details(
        self, row: PaymentDestinationModel
    ) -> DestinationDetails:
        snapshot = (
            row.id,
            row.encrypted_details,
            row.receiving_alias_id,
            row.revision,
        )
        result = await asyncio.to_thread(
            _decode_destination,
            snapshot,
            self.settings.configuration_encryption_key,
        )
        return result


def _decode_destination(
    snapshot: tuple[int, str, int | None, int], key: str
) -> DestinationDetails:
    id, encrypted, alias, revision = snapshot
    values = DestinationWrite.model_validate_json(decrypt(encrypted, key))
    return DestinationDetails(
        destination_id=id,
        receiving_alias_id=alias,
        revision=revision,
        **values.model_dump(exclude={"expected_revision"}),
    )


def _decode_destinations(
    snapshots: tuple[tuple[int, str, int | None, int], ...], key: str
) -> list[DestinationDetails]:
    return [_decode_destination(snapshot, key) for snapshot in snapshots]


def _missing(id: int) -> NotFoundException:
    return NotFoundException(
        message="مقصد پرداخت پیدا نشد.",
        message_code="payment_destination_not_found",
        entity="payment_destination",
        identifier="id",
        identifier_value=id,
    )
