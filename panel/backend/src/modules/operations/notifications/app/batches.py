"""Create customer notifications with bounded multi-recipient I/O."""

from datetime import UTC, datetime

import anyio
from papilio.errors.exceptions import ConflictException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import hash_sha256

from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.operations.notifications.app.commands import (
    changed,
    toman_text,
    unavailable_customer,
)
from src.modules.operations.notifications.domain.dtos import (
    CustomerNotificationBatch,
    CustomerNotificationEvent,
    DeliveryStatus,
    NotificationChannelMode,
)
from src.modules.operations.notifications.domain.models import (
    NotificationModel,
)
from src.modules.operations.notifications.domain.results import (
    NotificationAvailability,
)
from src.modules.operations.notifications.infra.mysql import (
    NotificationRepository,
)
from src.modules.operations.notifications.interfaces import (
    INotificationPolicyQuery,
)


class NotificationCreateBatchCommand:
    def __init__(
        self,
        repo: NotificationRepository,
        customers: ICustomerService,
        policy: INotificationPolicyQuery,
    ) -> None:
        self.repo, self.customers, self.policy = repo, customers, policy

    @handle_conflicts
    @transactional
    async def enqueue_many(self, data: CustomerNotificationBatch) -> None:
        customer_ids = sorted({item.customer_id for item in data.items})
        customers = await self.customers.locked_many(customer_ids)
        if {customer.id for customer in customers} != set(customer_ids):
            raise unavailable_customer(customer_ids[0])
        current = await self.policy.current()
        rows = await anyio.to_thread.run_sync(
            self.render_many,
            data.items,
            current,
            datetime.now(UTC).replace(tzinfo=None, microsecond=0),
        )
        existing = await self.repo.by_requests_many(data.items)
        self.validate_existing(rows, existing)
        await self.repo.ensure_many(rows)
        persisted = await self.repo.by_requests_many(data.items)
        if len(persisted) != len(rows):
            raise ConflictException(
                message="Notification batch was not persisted.",
                message_code="notification_batch_incomplete",
                unique_dict={},
            )
        self.validate_existing(rows, persisted)

    @staticmethod
    def render_many(
        items: list[CustomerNotificationEvent],
        current: NotificationAvailability,
        now: datetime,
    ) -> list[NotificationModel]:
        rows = []
        for item in items:
            event = item.event
            template = current.values.templates.get(event.kind)
            values = {
                "id": str(event.record_id),
                "amount_toman": toman_text(event.amount_rial)
                if event.amount_rial is not None
                else "",
                "status": event.status,
                "quota_gib": "",
                "used_gib": "",
                "remaining_gib": "",
                "expires_at": "",
                "renewal_price_toman": "",
                "generation": "",
                "threshold_code": "",
            }
            title = template.title.format_map(values) if template else ""
            body = template.body.format_map(values) if template else ""
            enabled = (
                current.values.enabled
                and template is not None
                and template.enabled
                and current.capacity_valid
                and len(title) <= 160
                and len(title + "\n" + body)
                <= current.values.max_message_chars
            )
            rows.append(
                NotificationModel(
                    customer_id=item.customer_id,
                    event_key=event.event_key,
                    event_hash=hash_sha256(event.model_dump_json()),
                    kind=event.kind,
                    record_id=event.record_id,
                    title=title,
                    body=body,
                    inbox_visible=enabled
                    and current.values.channel_mode
                    != NotificationChannelMode.TELEGRAM,
                    status=DeliveryStatus.PENDING
                    if enabled
                    and current.values.channel_mode
                    != NotificationChannelMode.INBOX
                    else DeliveryStatus.SKIPPED,
                    next_attempt_at=now,
                    error_code=None if enabled else "notification_suppressed",
                )
            )
        return rows

    @staticmethod
    def validate_existing(
        expected: list[NotificationModel],
        actual: list[NotificationModel],
    ) -> None:
        expected_by_identity = {
            (row.customer_id, row.event_key): row for row in expected
        }
        for row in actual:
            expected_row = expected_by_identity[
                (row.customer_id, row.event_key)
            ]
            if row.event_hash != expected_row.event_hash:
                raise changed("notification_event_reused", row.id)
