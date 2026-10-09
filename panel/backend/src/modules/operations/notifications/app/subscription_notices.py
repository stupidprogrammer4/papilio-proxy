import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import hash_sha256

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.infra.mysql import CustomerRepository
from src.modules.operations.notifications.app.commands import (
    invalid,
    toman_text,
    unavailable_customer,
)
from src.modules.operations.notifications.domain.dtos import (
    DeliveryStatus,
    NotificationChannelMode,
    SubscriptionNotificationEvent,
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


class SubscriptionNotificationBatchCommand:
    def __init__(
        self,
        repo: NotificationRepository,
        customers: CustomerRepository,
        policy: INotificationPolicyQuery,
        settings: PapilioSettings,
    ) -> None:
        self.repo, self.customers, self.policy, self.settings = (
            repo,
            customers,
            policy,
            settings,
        )

    @transactional
    async def enqueue_many(
        self, customer_id: int, events: list[SubscriptionNotificationEvent]
    ) -> None:
        capacity = self.settings.subscription_alerts_capacity
        if (
            len(events)
            > capacity.max_low_quota_rules + capacity.max_expiry_rules + 1
        ):
            raise invalid("subscription_alert_capacity")
        if not events:
            return
        customer = await self.customers.get_by_id(customer_id)
        if customer is None:
            raise unavailable_customer(customer_id)
        current = await self.policy.current()
        rows = await asyncio.to_thread(
            self.render, customer_id, events, current
        )
        await self.repo.ensure_many(rows)

    @staticmethod
    def render(
        customer_id: int,
        events: list[SubscriptionNotificationEvent],
        current: NotificationAvailability,
    ) -> list[NotificationModel]:
        rows = []
        for event in events:
            context = event.context
            values = {
                "id": str(event.record_id),
                "amount_toman": toman_text(event.amount_rial)
                if event.amount_rial is not None
                else "",
                "status": event.status,
                "generation": str(context.generation),
                "threshold_code": context.threshold_code,
                "quota_gib": format(
                    Decimal(context.quota_bytes) / Decimal(1024**3), ".2f"
                )
                if context.quota_bytes is not None
                else "نامحدود",
                "used_gib": format(
                    Decimal(context.used_bytes) / Decimal(1024**3), ".2f"
                ),
                "remaining_gib": format(
                    Decimal(context.remaining_bytes) / Decimal(1024**3), ".2f"
                )
                if context.remaining_bytes is not None
                else "نامحدود",
                "expires_at": context.expires_at.isoformat()
                if context.expires_at
                else "بدون انقضا",
                "renewal_price_toman": toman_text(context.renewal_price_rial)
                if context.renewal_price_rial is not None
                else "در دسترس نیست",
            }
            template = current.values.templates.get(event.kind)
            title = (
                template.title.format_map(values)
                if template is not None
                else ""
            )
            body = (
                template.body.format_map(values)
                if template is not None
                else ""
            )
            enabled = (
                current.capacity_valid
                and current.values.enabled
                and template is not None
                and template.enabled
                and len(title) <= 160
                and len(title + "\n" + body)
                <= current.values.max_message_chars
            )
            rows.append(
                NotificationModel(
                    customer_id=customer_id,
                    event_key=event.event_key,
                    event_hash=hash_sha256(event.model_dump_json()),
                    kind=event.kind,
                    record_id=event.record_id,
                    title=title,
                    body=body,
                    subscription_context=context.model_dump(mode="json"),
                    inbox_visible=enabled
                    and current.values.channel_mode
                    != NotificationChannelMode.TELEGRAM,
                    status=DeliveryStatus.PENDING
                    if enabled
                    and current.values.channel_mode
                    != NotificationChannelMode.INBOX
                    else DeliveryStatus.SKIPPED,
                    next_attempt_at=datetime.now(UTC).replace(
                        tzinfo=None, microsecond=0
                    ),
                    error_code=None if enabled else "notification_suppressed",
                )
            )
        return rows
