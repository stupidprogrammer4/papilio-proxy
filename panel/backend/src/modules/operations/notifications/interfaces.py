from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.operations.notifications.domain.dtos import (
    AdminNotificationSearch,
    CustomerNotificationBatch,
    ManualNotificationCreate,
    NotificationEvent,
    NotificationRecovery,
    NotificationSearch,
    SubscriptionNotificationEvent,
)
from src.modules.operations.notifications.domain.models import (
    NotificationAttemptModel,
    NotificationModel,
    NotificationRecoveryModel,
)
from src.modules.operations.notifications.domain.results import (
    DeliveryOutcome,
    NotificationAvailability,
    NotificationClaim,
)


class INotificationPolicyQuery(Protocol):
    def current(
        self, *, locked: bool = False
    ) -> Awaitable[NotificationAvailability]: ...


class INotificationQuery(Protocol):
    def get(self, id: int) -> Awaitable[NotificationModel]: ...
    def get_for_customer(
        self, id: int, customer_id: int
    ) -> Awaitable[NotificationModel]: ...
    def search(
        self, data: AdminNotificationSearch
    ) -> Awaitable[ServicePage[NotificationModel]]: ...
    def search_customer(
        self, customer_id: int, data: NotificationSearch
    ) -> Awaitable[ServicePage[NotificationModel]]: ...
    def due_ids(self) -> Awaitable[list[int]]: ...


class INotificationAttemptQuery(Protocol):
    def search(
        self, id: int, data: NotificationSearch
    ) -> Awaitable[ServicePage[NotificationAttemptModel]]: ...


class INotificationRecoveryQuery(Protocol):
    def search(
        self, id: int, data: NotificationSearch
    ) -> Awaitable[ServicePage[NotificationRecoveryModel]]: ...


class INotificationCreateCommand(Protocol):
    def enqueue(
        self, customer_id: int, data: NotificationEvent
    ) -> Awaitable[NotificationModel]: ...
    def manual(
        self, customer_id: int, data: ManualNotificationCreate, staff_id: int
    ) -> Awaitable[NotificationModel]: ...


class INotificationCreateBatchCommand(Protocol):
    def enqueue_many(
        self, data: CustomerNotificationBatch
    ) -> Awaitable[None]: ...


class INotificationInboxCommand(Protocol):
    def set_read(
        self, id: int, customer_id: int, is_read: bool
    ) -> Awaitable[NotificationModel]: ...


class INotificationDeliveryCommand(Protocol):
    def begin_send(
        self, id: int, token: str
    ) -> Awaitable[NotificationClaim | None]: ...
    def claim(self, id: int) -> Awaitable[NotificationClaim | None]: ...
    def finish(
        self, id: int, token: str, outcome: DeliveryOutcome
    ) -> Awaitable[bool]: ...
    def recover(
        self, id: int, staff_id: int, data: NotificationRecovery
    ) -> Awaitable[NotificationModel]: ...


class INotificationTransport(Protocol):
    def send(self, claim: NotificationClaim) -> Awaitable[DeliveryOutcome]: ...


class INotificationDeliveryHandler(Protocol):
    def deliver(self, id: int) -> Awaitable[bool]: ...


class ISubscriptionNotificationBatchCommand(Protocol):
    def enqueue_many(
        self, customer_id: int, events: list[SubscriptionNotificationEvent]
    ) -> Awaitable[None]: ...
