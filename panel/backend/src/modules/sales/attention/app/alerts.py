from datetime import UTC, datetime, timedelta

from papilio.infra.db.tools.decorators import transactional

from src.config.settings import PapilioSettings
from src.modules.operations.notifications.domain.context import (
    SubscriptionNoticeContext,
)
from src.modules.operations.notifications.domain.dtos import (
    NotificationKind,
    SubscriptionNotificationEvent,
)
from src.modules.operations.notifications.interfaces import (
    ISubscriptionNotificationBatchCommand,
)
from src.modules.operations.preferences.interfaces import IPreferencesService
from src.modules.sales.subscriptions.domain.models import SubscriptionModel
from src.modules.sales.subscriptions.domain.results import (
    SubscriptionRenewalQuote,
)


class SubscriptionAlertCommand:
    def __init__(
        self,
        preferences: IPreferencesService,
        settings: PapilioSettings,
        notifications: ISubscriptionNotificationBatchCommand,
    ) -> None:
        self.preferences, self.settings, self.notifications = (
            preferences,
            settings,
            notifications,
        )

    @transactional
    async def publish(
        self,
        subscription: SubscriptionModel,
        quote: SubscriptionRenewalQuote,
        now: datetime,
    ) -> bool:
        policy = (await self.preferences.current()).values.subscription_alerts
        capacity = self.settings.subscription_alerts_capacity
        if policy is None or not policy.enabled:
            return False
        if (
            len(policy.low_quota) > capacity.max_low_quota_rules
            or len(policy.expiry_hours) > capacity.max_expiry_rules
            or any(
                value > capacity.max_expiry_hours
                for value in policy.expiry_hours
            )
        ):
            return True
        if subscription.status not in {"active", "expired", "exhausted"}:
            return True
        matches: list[tuple[str, NotificationKind, str]] = []
        remaining = (
            max(0, subscription.quota_bytes - subscription.used_bytes)
            if subscription.quota_bytes is not None
            else None
        )
        if remaining is not None and subscription.quota_bytes is not None:
            for rule in policy.low_quota:
                conditions = []
                if rule.remaining_bytes is not None:
                    conditions.append(remaining <= rule.remaining_bytes)
                if rule.remaining_percent_bps is not None:
                    conditions.append(
                        remaining * 10000
                        <= subscription.quota_bytes
                        * rule.remaining_percent_bps
                    )
                if any(conditions) if rule.mode == "any" else all(conditions):
                    matches.append(
                        (
                            "quota:" + rule.code,
                            NotificationKind.VOLUME_LOW,
                            "حجم باقی‌مانده کم است",
                        )
                    )
        if subscription.expires_at is not None:
            for hours in policy.expiry_hours:
                if subscription.expires_at <= now + timedelta(hours=hours):
                    matches.append(
                        (
                            "expiry:" + str(hours),
                            NotificationKind.EXPIRY_SOON,
                            "پایان نزدیک اعتبار",
                        )
                    )
        if (
            policy.renewal_opportunity
            and quote.available
            and subscription.entitlement_kind == "paid"
        ):
            due = (
                remaining == 0
                or subscription.expires_at is not None
                and subscription.expires_at <= now
            )
            near = bool(matches)
            if due or near:
                matches.append(
                    (
                        "renewal",
                        NotificationKind.RENEWAL_AVAILABLE,
                        "فرصت تمدید سرویس",
                    )
                )
        events = [
            SubscriptionNotificationEvent(
                event_key=f"subscription-alert:{subscription.id}:{subscription.renewal_count}:{code}",
                kind=kind,
                record_id=subscription.id,
                amount_rial=quote.price_rial if quote.available else None,
                status=status,
                context=SubscriptionNoticeContext(
                    subscription_id=subscription.id,
                    generation=subscription.renewal_count,
                    threshold_code=code,
                    quota_bytes=subscription.quota_bytes,
                    used_bytes=subscription.used_bytes,
                    remaining_bytes=remaining,
                    expires_at=subscription.expires_at,
                    renewal_price_rial=quote.price_rial
                    if quote.available
                    else None,
                    captured_at=now.replace(tzinfo=UTC),
                ),
            )
            for code, kind, status in matches
        ]
        await self.notifications.enqueue_many(subscription.customer_id, events)
        return True
