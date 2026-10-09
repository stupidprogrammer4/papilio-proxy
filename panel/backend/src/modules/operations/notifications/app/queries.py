from datetime import UTC, datetime

from papilio.errors.exceptions import NotFoundException

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.operations.automation.domain.dtos import ScheduleKey
from src.modules.operations.automation.interfaces import IAutomationPolicyQuery
from src.modules.operations.notifications.domain.dtos import (
    AdminNotificationSearch,
    DeliveryStatus,
    NotificationKind,
    NotificationSearch,
)
from src.modules.operations.notifications.domain.models import (
    NotificationAttemptModel,
    NotificationModel,
    NotificationRecoveryModel,
)
from src.modules.operations.notifications.domain.results import (
    NotificationAvailability,
)
from src.modules.operations.notifications.infra.mysql import (
    NotificationAttemptRepository,
    NotificationRecoveryRepository,
    NotificationRepository,
)
from src.modules.operations.notifications.interfaces import (
    INotificationPolicyQuery,
)
from src.modules.operations.preferences.interfaces import IPreferencesService


class NotificationPolicyQuery:
    def __init__(
        self, preferences: IPreferencesService, settings: PapilioSettings
    ) -> None:
        self.preferences, self.settings = preferences, settings

    async def current(
        self, *, locked: bool = False
    ) -> NotificationAvailability:
        preferences = await self.preferences.current(locked=locked)
        p = preferences.values.notifications
        assert p is not None
        c = self.settings.notifications
        return NotificationAvailability(
            p,
            p.max_attempts <= c.max_attempts
            and p.max_retry_seconds <= c.max_retry_seconds
            and p.lease_seconds <= c.max_lease_seconds
            and p.lease_seconds > c.timeout_seconds + c.lease_margin_seconds
            and p.max_message_chars <= c.max_message_chars,
            c.outbound_enabled,
            tuple(NotificationKind),
        )


class NotificationQuery:
    def __init__(
        self,
        repo: NotificationRepository,
        settings: PapilioSettings,
        policies: IAutomationPolicyQuery,
        notifications: INotificationPolicyQuery,
    ) -> None:
        self.repo, self.settings, self.policies = repo, settings, policies
        self.notifications = notifications

    async def get(self, id: int) -> NotificationModel:
        row = await self.repo.get_by_id(id)
        if row is None:
            raise missing_notification(id)
        return row

    async def get_for_customer(
        self, id: int, customer_id: int
    ) -> NotificationModel:
        row = await self.repo.owned(id, customer_id)
        if row is None:
            raise missing_notification(id)
        return row

    async def search(
        self, data: AdminNotificationSearch
    ) -> ServicePage[NotificationModel]:
        limit = page_size(self.settings, data.per_page)
        rows = await self.repo.page(
            data.q,
            data.kind,
            data.status,
            data.is_read,
            data.customer_id,
            (data.page - 1) * limit,
            limit,
        )
        return service_page(rows, limit)

    async def search_customer(
        self, customer_id: int, data: NotificationSearch
    ) -> ServicePage[NotificationModel]:
        limit = page_size(self.settings, data.per_page)
        rows = await self.repo.customer_page(
            customer_id,
            data.q,
            data.kind,
            data.is_read,
            (data.page - 1) * limit,
            limit,
        )
        return service_page(rows, limit)

    async def due_ids(self) -> list[int]:
        schedule = await self.policies.schedule(ScheduleKey.NOTIFICATIONS)
        if not schedule.runnable:
            return []
        policy = await self.notifications.current()
        enabled = (
            policy.capacity_valid
            and policy.outbound_available
            and policy.values.enabled
            and policy.values.delivery_enabled
        )
        statuses = (
            (DeliveryStatus.PENDING, DeliveryStatus.RETRY) if enabled else ()
        )
        kinds = tuple(
            kind.value
            for kind, template in policy.values.templates.items()
            if template.enabled
        )
        rows = await self.repo.due_ids(
            datetime.now(UTC).replace(tzinfo=None, microsecond=0),
            statuses,
            DeliveryStatus.PROCESSING,
            kinds,
            schedule.values.batch_size,
        )
        return rows


class NotificationAttemptQuery:
    def __init__(
        self, repo: NotificationAttemptRepository, settings: PapilioSettings
    ) -> None:
        self.repo, self.settings = repo, settings

    async def search(
        self, id: int, data: NotificationSearch
    ) -> ServicePage[NotificationAttemptModel]:
        limit = page_size(self.settings, data.per_page)
        rows = await self.repo.page(id, (data.page - 1) * limit, limit)
        return service_page(rows, limit)


class NotificationRecoveryQuery:
    def __init__(
        self, repo: NotificationRecoveryRepository, settings: PapilioSettings
    ) -> None:
        self.repo, self.settings = repo, settings

    async def search(
        self, id: int, data: NotificationSearch
    ) -> ServicePage[NotificationRecoveryModel]:
        limit = page_size(self.settings, data.per_page)
        rows = await self.repo.page(id, (data.page - 1) * limit, limit)
        return service_page(rows, limit)


def missing_notification(id: int) -> NotFoundException:
    return NotFoundException(
        message="اعلان در این حساب پیدا نشد.",
        message_code="notification_not_found",
        entity="notification",
        identifier="id",
        identifier_value=id,
    )
