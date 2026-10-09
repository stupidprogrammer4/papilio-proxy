from papilio.errors.exceptions import ConflictException, NotFoundException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.sales.loyalty.domain.dtos import (
    CustomerTierWrite,
    LoyaltyPolicy,
    LoyaltyPolicyWrite,
    LoyaltySearch,
)
from src.modules.sales.loyalty.domain.models import (
    CustomerTierModel,
    LoyaltyPolicyModel,
)
from src.modules.sales.loyalty.domain.results import LoyaltyPolicyRead
from src.modules.sales.loyalty.infra.mysql import (
    CustomerTierRepository,
    LoyaltyPolicyRepository,
)


class CustomerTierService:
    def __init__(
        self, repo: CustomerTierRepository, settings: PapilioSettings
    ) -> None:
        self.repo, self.settings = repo, settings

    @handle_conflicts
    @transactional
    async def create(self, data: CustomerTierWrite) -> CustomerTierModel:
        if self.settings.loyalty is None:
            raise ConflictException(
                message="Loyalty is not configured",
                message_code="loyalty_unavailable",
                unique_dict={},
            )
        rows = await self.repo.page(0, self.settings.loyalty.max_tiers)
        if rows.total_items >= self.settings.loyalty.max_tiers:
            raise ConflictException(
                message="Tier capacity exceeded",
                message_code="tier_capacity",
                unique_dict={},
            )
        result = await self.repo.create(
            CustomerTierModel(**data.model_dump(exclude={"expected_revision"}))
        )
        return result

    @handle_conflicts
    @transactional
    async def update(
        self, id: int, data: CustomerTierWrite
    ) -> CustomerTierModel:
        row = await self.repo.locked(id)
        if row is None:
            raise NotFoundException(
                message="Tier not found",
                message_code="tier_not_found",
                entity="tier",
                identifier="id",
                identifier_value=id,
            )
        if row.revision != data.expected_revision:
            raise ConflictException(
                message="Refresh the changed tier",
                message_code="tier_revision_conflict",
                unique_dict={"id": id},
            )
        result = await self.repo.change(
            row,
            CustomerTierModel.patch(
                code=data.code,
                title=data.title,
                minimum_bytes=data.minimum_bytes,
                discount_bps=data.discount_bps,
                is_enabled=data.is_enabled,
                revision=row.revision + 1,
            ),
        )
        return result

    async def search(
        self, data: LoyaltySearch
    ) -> ServicePage[CustomerTierModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page((data.page - 1) * limit, limit)
        return service_page(result, limit)

    @transactional
    async def initialize(self) -> None:
        settings = self.settings.loyalty
        if settings is None:
            raise ConflictException(
                message="Loyalty is not configured",
                message_code="loyalty_unavailable",
                unique_dict={},
            )
        if len(settings.initial_tiers) > settings.max_tiers:
            raise ConflictException(
                message="Initial tiers exceed capacity",
                message_code="tier_capacity",
                unique_dict={},
            )
        await self.repo.seed_missing(
            [
                CustomerTierModel(
                    **data.model_dump(exclude={"expected_revision"}),
                    revision=1,
                )
                for data in settings.initial_tiers
            ]
        )

    async def candidates(
        self, *, locked: bool = False
    ) -> list[CustomerTierModel]:
        if self.settings.loyalty is None:
            return []
        if locked:
            current = await self.repo.candidates_current(
                self.settings.loyalty.max_tiers + 1
            )
            if len(current) > self.settings.loyalty.max_tiers:
                raise ConflictException(
                    message="Tier capacity exceeded",
                    message_code="tier_capacity",
                    unique_dict={},
                )
            return current
        rows = await self.repo.page(0, self.settings.loyalty.max_tiers + 1)
        if rows.total_items > self.settings.loyalty.max_tiers:
            raise ConflictException(
                message="Tier capacity exceeded",
                message_code="tier_capacity",
                unique_dict={},
            )
        return list(rows.items)


class LoyaltyPolicyService:
    def __init__(
        self, repo: LoyaltyPolicyRepository, settings: PapilioSettings
    ) -> None:
        self.repo, self.settings = repo, settings

    @transactional
    async def initialize(self) -> None:
        settings = self.settings.loyalty
        if settings is None:
            raise ConflictException(
                message="Loyalty is not configured",
                message_code="loyalty_unavailable",
                unique_dict={},
            )
        await self.repo.seed_missing(
            LoyaltyPolicyModel(
                code="current",
                values_json=settings.defaults.model_dump_json(),
                revision=1,
            )
        )

    async def current(self, *, locked: bool = False) -> LoyaltyPolicyRead:
        row = await self.repo.current("current", locked)
        if row is None:
            if self.settings.loyalty is None:
                raise ConflictException(
                    message="Loyalty is not configured",
                    message_code="loyalty_unavailable",
                    unique_dict={},
                )
            return LoyaltyPolicyRead(
                revision=1,
                values=LoyaltyPolicy.model_validate(
                    self.settings.loyalty.defaults
                ),
            )
        return LoyaltyPolicyRead(
            revision=row.revision,
            values=LoyaltyPolicy.model_validate_json(row.values_json),
        )

    @handle_conflicts(message_code="loyalty_revision_conflict")
    @transactional
    async def update(self, data: LoyaltyPolicyWrite) -> LoyaltyPolicyRead:
        settings = self.settings.loyalty
        if settings is None or (
            data.values.enabled
            and len(data.values.unlimited_plan_bytes)
            > settings.max_plan_overrides
        ):
            raise ConflictException(
                message="Loyalty policy exceeds configured capacity",
                message_code="loyalty_capacity",
                unique_dict={},
            )
        row = await self.repo.current("current", True)
        if row is None:
            if data.expected_revision != 1:
                raise ConflictException(
                    message="Refresh loyalty policy",
                    message_code="loyalty_revision_conflict",
                    unique_dict={},
                )
            row = await self.repo.create(
                LoyaltyPolicyModel(
                    code="current",
                    values_json=data.values.model_dump_json(),
                    revision=2,
                )
            )
        else:
            if row.revision != data.expected_revision:
                raise ConflictException(
                    message="Refresh loyalty policy",
                    message_code="loyalty_revision_conflict",
                    unique_dict={},
                )
            row = await self.repo.change(
                row,
                LoyaltyPolicyModel.patch(
                    values_json=data.values.model_dump_json(),
                    revision=row.revision + 1,
                ),
            )
        return LoyaltyPolicyRead(
            revision=row.revision,
            values=LoyaltyPolicy.model_validate_json(row.values_json),
        )
