from datetime import UTC, datetime, timedelta

from papilio.errors.exceptions import NotFoundException
from papilio.infra.db.tools.decorators import transactional

from src.config.settings import PapilioSettings
from src.modules.billing.wallet.interfaces import IWalletCommand
from src.modules.operations.notifications.domain.dtos import (
    NotificationEvent,
    NotificationKind,
)
from src.modules.operations.notifications.interfaces import (
    INotificationCreateCommand,
)
from src.modules.operations.preferences.interfaces import IPreferencesService
from src.modules.sales.attention.domain.models import (
    SubscriptionAttentionModel,
)
from src.modules.sales.attention.infra.mysql import (
    SubscriptionAttentionRepository,
)
from src.modules.sales.attention.interfaces import ISubscriptionAlertCommand
from src.modules.sales.subscriptions.infra.mysql import SubscriptionRepository
from src.modules.sales.subscriptions.interfaces import (
    ISubscriptionRenewalQuoteQuery,
)


class SubscriptionAttentionCommand:
    def __init__(
        self,
        subscriptions: SubscriptionRepository,
        wallets: IWalletCommand,
        renewal_quotes: ISubscriptionRenewalQuoteQuery,
        attention: SubscriptionAttentionRepository,
        settings: PapilioSettings,
        preferences: IPreferencesService,
        notifications: INotificationCreateCommand,
        alerts: ISubscriptionAlertCommand,
    ) -> None:
        self.subscriptions = subscriptions
        self.wallets = wallets
        self.renewal_quotes = renewal_quotes
        self.attention = attention
        self.settings = settings
        self.preferences = preferences
        self.notifications = notifications
        self.alerts = alerts

    @transactional
    async def check(self, subscription_id: int) -> SubscriptionAttentionModel:
        subscription = await self.subscriptions.locked(subscription_id)
        if subscription is None:
            raise NotFoundException(
                message="اشتراک پیدا نشد.",
                message_code="subscription_not_found",
                entity="subscription",
                identifier="id",
                identifier_value=subscription_id,
            )
        quote = await self.renewal_quotes.get(subscription, locked=True)
        balance = await self.wallets.balance(quote.payer_customer_id)
        now = datetime.now(UTC).replace(tzinfo=None)
        preferences = (await self.preferences.current()).values
        warning_until = now + timedelta(
            hours=preferences.subscription_expiry_warning_hours
        )
        if subscription.status == "failed":
            status = "provisioning_failed"
        elif subscription.status == "pending_provision":
            since = subscription.renewal_checked_at or subscription.created_at
            assert since is not None
            status = (
                "provisioning_delayed"
                if since
                <= now
                - timedelta(minutes=preferences.provisioning_attention_minutes)
                else "clear"
            )
        elif (
            subscription.status in {"active", "exhausted"}
            and subscription.quota_bytes is not None
            and subscription.used_bytes >= subscription.quota_bytes
        ):
            if subscription.auto_renew and not quote.available:
                status = "renewal_unavailable"
            elif subscription.auto_renew and balance < quote.price_rial:
                status = "renewal_unfunded"
            else:
                status = "quota_exhausted"
        elif (
            subscription.status in {"active", "expired"}
            and subscription.expires_at is not None
            and subscription.expires_at <= warning_until
        ):
            if subscription.auto_renew and not quote.available:
                status = "renewal_unavailable"
            elif subscription.auto_renew and balance < quote.price_rial:
                status = "renewal_unfunded"
            elif subscription.expires_at <= now:
                status = "expired"
            else:
                status = "expiry_soon"
        else:
            status = "clear"
        result = await self.attention.store(
            SubscriptionAttentionModel(
                subscription_id=subscription_id,
                status=status,
                wallet_balance_rial=balance,
                payer_customer_id=quote.payer_customer_id,
                renewal_price_rial=quote.price_rial,
                renewal_available=quote.available,
                checked_at=now,
            )
        )
        new_alert_policy = await self.alerts.publish(subscription, quote, now)
        if status in {
            "expiry_soon",
            "renewal_unfunded",
            "provisioning_failed",
        } and not (status == "expiry_soon" and new_alert_policy):
            await self.notifications.enqueue(
                subscription.customer_id,
                NotificationEvent(
                    event_key=f"attention:{subscription_id}:{subscription.renewal_count}:{status}",
                    kind=NotificationKind(status),
                    status={
                        "expiry_soon": "پایان نزدیک اعتبار",
                        "renewal_unfunded": "موجودی ناکافی تمدید",
                        "provisioning_failed": "نیاز به پیگیری آماده‌سازی",
                    }[status],
                    record_id=subscription_id,
                ),
            )
        return result
