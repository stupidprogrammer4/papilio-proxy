from datetime import UTC, datetime

from papilio.errors.exceptions import ConflictException, ValidationException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from taskiq.decor import AsyncTaskiqDecoratedTask

from src.config.settings import PapilioSettings
from src.modules.operations.automation.app.defaults import AutomationDefaults
from src.modules.operations.automation.domain.dtos import (
    ScheduleKey,
    SchedulePolicy,
    ScheduleWrite,
)
from src.modules.operations.automation.domain.models import (
    AutomationRegistrationModel,
    AutomationRevisionModel,
)
from src.modules.operations.automation.domain.results import AutomationSchedule
from src.modules.operations.automation.infra.mysql import (
    AutomationRegistrationRepository,
    AutomationRevisionRepository,
)
from src.modules.operations.automation.interfaces import IRuntimeScheduleStore


class AutomationPolicyCommand:
    def __init__(
        self,
        registrations: AutomationRegistrationRepository,
        revisions: AutomationRevisionRepository,
        settings: PapilioSettings,
    ) -> None:
        self.registrations = registrations
        self.revisions = revisions
        self.settings = settings
        self.defaults = AutomationDefaults(settings)

    @handle_conflicts(message_code="automation_revision_conflict")
    @transactional
    async def write(
        self, key: ScheduleKey, data: ScheduleWrite, staff_id: int
    ) -> AutomationSchedule:
        fallback = self.defaults.schedule(key)
        await self.registrations.ensure_default(
            AutomationRegistrationModel(
                key=key.value, policy_json=fallback.values.model_dump_json()
            )
        )
        row = await self.registrations.locked(key.value)
        assert row is not None
        current = (
            fallback.values
            if row is None
            else SchedulePolicy.model_validate_json(row.policy_json)
        )
        revision = 0 if row is None else row.revision
        if revision != data.expected_revision:
            raise ConflictException(
                message="زمان‌بندی تغییر کرده است؛ نسخهٔ تازه را بررسی کنید.",
                message_code="automation_revision_conflict",
                unique_dict={"revision": revision},
            )
        if not self.defaults.capacity_accepts(data.values):
            raise ValidationException(
                message="زمان‌بندی از سقف عملیاتی بیشتر است.",
                message_code="automation_policy_capacity",
                loc=["values"],
                input=data.values.model_dump(),
                ctx={},
            )
        if (current.recheck_seconds is None) != (
            data.values.recheck_seconds is None
        ):
            raise ValidationException(
                message="این عملیات سیاست بررسی مجدد متفاوتی دارد.",
                message_code="automation_recheck_mode",
                loc=["values", "recheck_seconds"],
                input=data.values.recheck_seconds,
                ctx={},
            )
        if current == data.values:
            return AutomationSchedule(
                key,
                fallback.scope,
                current,
                revision,
                None if row is None else row.applied_revision,
                None if row is None else row.registered_at,
                self.defaults.capacity_accepts(current),
            )
        await self.revisions.create(
            AutomationRevisionModel(
                key=key.value,
                revision=revision + 1,
                policy_json=data.values.model_dump_json(),
                staff_id=staff_id,
                reason=data.reason,
            )
        )
        if row is None:
            row = await self.registrations.create(
                AutomationRegistrationModel(
                    key=key.value,
                    revision=revision + 1,
                    policy_json=data.values.model_dump_json(),
                )
            )
        else:
            await self.registrations.update_row_by_id(
                row.id,
                AutomationRegistrationModel.patch(
                    revision=revision + 1,
                    policy_json=data.values.model_dump_json(),
                ),
            )
        return AutomationSchedule(
            key,
            fallback.scope,
            data.values,
            revision + 1,
            row.applied_revision,
            row.registered_at,
            self.defaults.capacity_accepts(data.values),
        )


class AutomationRegistrationCommand:
    def __init__(
        self,
        repo: AutomationRegistrationRepository,
        store: IRuntimeScheduleStore,
        settings: PapilioSettings,
    ) -> None:
        self.repo = repo
        self.store = store
        self.defaults = AutomationDefaults(settings)

    @handle_conflicts
    @transactional
    async def reconcile(
        self, key: ScheduleKey, task: AsyncTaskiqDecoratedTask
    ) -> int:
        defaults = self.defaults.schedule(key)
        await self.repo.ensure_default(
            AutomationRegistrationModel(
                key=key.value, policy_json=defaults.values.model_dump_json()
            )
        )
        row = await self.repo.locked(key.value)
        assert row is not None
        values = SchedulePolicy.model_validate_json(row.policy_json)
        if not self.defaults.capacity_accepts(values):
            values.enabled = False
        await self.store.reconcile(key, task, values, row.revision)
        await self.repo.update_row_by_id(
            row.id,
            AutomationRegistrationModel.patch(
                applied_revision=row.revision,
                registered_at=datetime.now(UTC).replace(tzinfo=None),
            ),
        )
        return row.revision
