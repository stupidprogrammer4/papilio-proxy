from papilio.errors.exceptions import (
    ConflictException,
    NotFoundException,
    ValidationException,
)
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.network.ip_limits.domain.dtos import IpLimitChoice
from src.modules.network.ip_limits.domain.purchased import IpLimitCapacityRead
from src.modules.network.routing.interfaces import IHostGroupService
from src.modules.operations.preferences.interfaces import IPreferencesService
from src.modules.sales.catalog.domain.dtos import (
    PlanCreate,
    PlanSearch,
    PlanSetActive,
    PlanUpdate,
)
from src.modules.sales.catalog.domain.models import PlanModel
from src.modules.sales.catalog.domain.policies import (
    FulfillmentPolicy,
    QuotaPolicy,
)
from src.modules.sales.catalog.domain.results import PlanPolicyDefaults
from src.modules.sales.catalog.infra.mysql import PlanRepository


class PlanService:
    def __init__(
        self,
        repo: PlanRepository,
        settings: PapilioSettings,
        groups: IHostGroupService,
        preferences: IPreferencesService,
    ) -> None:
        self.repo = repo
        self.settings = settings
        self.preferences = preferences
        self.groups = groups

    async def policy_defaults(self) -> PlanPolicyDefaults:
        current = (await self.preferences.current()).values
        return PlanPolicyDefaults(
            ip_limit_capacity=IpLimitCapacityRead.model_validate(
                self.settings.ip_limits.model_dump()
            ),
            quota_policy=current.quota_policy or self.settings.usage.policy,
            fulfillment=current.fulfillment
            or self.settings.fulfillment.policy,
            ip_limit=IpLimitChoice.model_validate(
                current.ip_defaults.model_dump()
            ),
        )

    @handle_conflicts
    @transactional
    async def create(self, data: PlanCreate) -> PlanModel:
        self._check_policies(
            data.fulfillment, data.ip_limit, data.quota_policy
        )
        await self._check_duration(data.duration_days)
        if data.group_id is not None:
            await self.groups.get(data.group_id)
        existing = await self.repo.get_by_code(data.code)
        if existing is not None:
            raise ConflictException(
                message="کد پلن تکراری است.",
                message_code="plan_code_exists",
                unique_dict={"code": data.code},
            )
        result = await self.repo.create(
            PlanModel(
                **data.model_dump(
                    exclude={"fulfillment", "ip_limit", "quota_policy"}
                ),
                quota_policy_json=data.quota_policy.model_dump_json()
                if data.quota_policy is not None
                else None,
                fulfillment_json=data.fulfillment.model_dump_json()
                if data.fulfillment is not None
                else None,
                ip_limit_json=data.ip_limit.model_dump_json()
                if data.ip_limit is not None
                else None,
                is_active=False,
            )
        )
        return result

    @transactional
    async def update(self, id: int, data: PlanUpdate) -> PlanModel:
        self._check_policies(
            data.fulfillment, data.ip_limit, data.quota_policy
        )
        if data.group_id is not None:
            await self.groups.get(data.group_id)
        if data.duration_days is not None:
            await self._check_duration(data.duration_days)
        existing = await self.repo.locked(id)
        if existing is None:
            raise _missing(id)
        quota = (
            data.quota_bytes
            if "quota_bytes" in data.model_fields_set
            else existing.quota_bytes
        )
        duration = (
            data.duration_days
            if "duration_days" in data.model_fields_set
            else existing.duration_days
        )
        if quota is None and duration is None:
            raise ValidationException(
                message="پلن باید محدودیت حجم یا مدت داشته باشد.",
                message_code="plan_limit_required",
                loc=["quota_bytes"],
                input=None,
            )
        changes = data.model_dump(
            exclude_unset=True,
            exclude={"fulfillment", "ip_limit", "quota_policy"},
        )
        if "quota_policy" in data.model_fields_set:
            changes["quota_policy_json"] = (
                data.quota_policy.model_dump_json()
                if data.quota_policy is not None
                else None
            )
        if "fulfillment" in data.model_fields_set:
            changes["fulfillment_json"] = (
                data.fulfillment.model_dump_json()
                if data.fulfillment is not None
                else None
            )
        if "ip_limit" in data.model_fields_set:
            changes["ip_limit_json"] = (
                data.ip_limit.model_dump_json()
                if data.ip_limit is not None
                else None
            )
        result = await self.repo.update_existing(
            existing, PlanModel.patch(**changes)
        )
        return result

    @transactional
    async def set_active(self, id: int, data: PlanSetActive) -> PlanModel:
        existing = await self.repo.get_by_id(id)
        if existing is None:
            raise _missing(id)
        result = await self.repo.update_existing(
            existing, PlanModel.patch(is_active=data.is_active)
        )
        return result

    async def get_active(self, id: int) -> PlanModel:
        result = await self.repo.get_by_id(id)
        if result is None or not result.is_active:
            raise _missing(id)
        return result

    async def get(self, id: int) -> PlanModel:
        result = await self.repo.get_by_id(id)
        if result is None:
            raise _missing(id)
        return result

    async def search(self, data: PlanSearch) -> ServicePage[PlanModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.search_page(
            q=data.q,
            active=data.active,
            offset=(data.page - 1) * limit,
            limit=limit,
        )
        return service_page(result, limit)

    async def _check_duration(self, days: int | None) -> None:
        if days is None:
            return
        maximum = (
            await self.preferences.current()
        ).values.max_plan_duration_days
        if days > maximum:
            raise ValidationException(
                message="مدت پلن از سقف تنظیم‌شده بیشتر است.",
                message_code="plan_duration_exceeds_policy",
                loc=["duration_days"],
                input=days,
                ctx={"maximum": maximum},
            )

    def _check_policies(
        self,
        fulfillment: FulfillmentPolicy | None,
        ip_limit: IpLimitChoice | None,
        quota_policy: QuotaPolicy | None,
    ) -> None:
        if quota_policy is not None and (
            quota_policy.grant_bytes > self.settings.usage.max_grant_bytes
            or quota_policy.grant_seconds
            > self.settings.usage.max_grant_seconds
        ):
            raise ValidationException(
                message="سیاست سهمیه از سقف عملیاتی بیشتر است.",
                message_code="usage_grant_capacity",
                loc=["quota_policy"],
                input=quota_policy.model_dump(),
                ctx={},
            )
        capacity = self.settings.fulfillment
        ceilings = self.settings.ip_limits
        if fulfillment is not None and (
            fulfillment.max_attempts > capacity.max_attempts
            or fulfillment.claim_seconds > capacity.max_claim_seconds
            or fulfillment.minimum_successes > capacity.max_targets
        ):
            raise ValidationException(
                message="سیاست تحویل از سقف عملیاتی بیشتر است.",
                message_code="fulfillment_capacity",
                loc=["fulfillment"],
                input=fulfillment.model_dump(),
                ctx={},
            )
        if ip_limit is not None and (
            ip_limit.max_ips > ceilings.max_ips_ceiling
            or ip_limit.lease_seconds > ceilings.max_lease_seconds
            or ip_limit.ban_seconds > ceilings.max_ban_seconds
        ):
            raise ValidationException(
                message="سیاست آی‌پی از سقف عملیاتی بیشتر است.",
                message_code="ip_policy_capacity",
                loc=["ip_limit"],
                input=ip_limit.model_dump(),
                ctx={},
            )


def _missing(id: int) -> NotFoundException:
    return NotFoundException(
        message="پلن پیدا نشد.",
        message_code="plan_not_found",
        entity="plan",
        identifier="id",
        identifier_value=id,
    )
