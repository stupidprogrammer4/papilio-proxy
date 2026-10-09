from collections.abc import AsyncIterator

import aiohttp
from dishka import Provider, Scope, provide

from src.config.settings import PapilioSettings
from src.modules.operations.notifications.app.commands import (
    NotificationCreateCommand,
    NotificationDeliveryCommand,
    NotificationInboxCommand,
)
from src.modules.operations.notifications.app.handlers import (
    NotificationDeliveryHandler,
)
from src.modules.operations.notifications.app.queries import (
    NotificationAttemptQuery,
    NotificationPolicyQuery,
    NotificationQuery,
    NotificationRecoveryQuery,
)
from src.modules.operations.notifications.app.subscription_notices import (
    SubscriptionNotificationBatchCommand,
)
from src.modules.operations.notifications.infra.mysql import (
    NotificationAttemptRepository,
    NotificationRecoveryRepository,
    NotificationRepository,
)
from src.modules.operations.notifications.infra.transport import (
    AiogramNotificationTransport,
)
from src.modules.operations.notifications.interfaces import (
    INotificationAttemptQuery,
    INotificationCreateCommand,
    INotificationDeliveryCommand,
    INotificationDeliveryHandler,
    INotificationInboxCommand,
    INotificationPolicyQuery,
    INotificationQuery,
    INotificationRecoveryQuery,
    INotificationTransport,
    ISubscriptionNotificationBatchCommand,
)
from src.modules.operations.notifications.tasks.schedulers.delivery import (
    DeliverNotification,
    ScanNotifications,
)


class NotificationProvider(Provider):
    subscription_batch = provide(
        SubscriptionNotificationBatchCommand,
        provides=ISubscriptionNotificationBatchCommand,
    )
    scope = Scope.REQUEST
    repo = provide(NotificationRepository)
    attempts = provide(NotificationAttemptRepository)
    recoveries = provide(NotificationRecoveryRepository)
    policy = provide(
        NotificationPolicyQuery, provides=INotificationPolicyQuery
    )
    query = provide(NotificationQuery, provides=INotificationQuery)
    attempt_query = provide(
        NotificationAttemptQuery, provides=INotificationAttemptQuery
    )
    recovery_query = provide(
        NotificationRecoveryQuery, provides=INotificationRecoveryQuery
    )
    create = provide(
        NotificationCreateCommand, provides=INotificationCreateCommand
    )
    inbox = provide(
        NotificationInboxCommand, provides=INotificationInboxCommand
    )
    delivery = provide(
        NotificationDeliveryCommand, provides=INotificationDeliveryCommand
    )

    @provide(scope=Scope.APP, provides=INotificationTransport)
    async def transport(
        self, settings: PapilioSettings
    ) -> AsyncIterator[INotificationTransport]:
        policy = settings.notifications.transport_pool()
        connector = aiohttp.TCPConnector(
            limit=policy.max_connections,
            limit_per_host=policy.max_connections_per_host,
            keepalive_timeout=policy.keepalive_seconds,
            ttl_dns_cache=policy.dns_cache_seconds,
        )
        async with aiohttp.ClientSession(
            connector=connector,
            cookie_jar=aiohttp.DummyCookieJar(),
            auto_decompress=False,
            trust_env=False,
        ) as session:
            yield AiogramNotificationTransport(settings, session)

    handler = provide(
        NotificationDeliveryHandler, provides=INotificationDeliveryHandler
    )
    task = provide(DeliverNotification)
    scan_task = provide(ScanNotifications)
