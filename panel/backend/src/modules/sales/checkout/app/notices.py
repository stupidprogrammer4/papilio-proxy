from src.modules.operations.notifications.domain.context import (
    CheckoutNoticeAction,
)
from src.modules.operations.notifications.domain.dtos import (
    NotificationEvent,
    NotificationKind,
)
from src.modules.operations.notifications.interfaces import (
    INotificationCreateCommand,
)
from src.modules.sales.checkout.domain.models import CheckoutIntentModel
from src.modules.sales.checkout.infra.mysql import CheckoutIntentRepository


class CheckoutNoticeCommand:
    def __init__(self, notifications: INotificationCreateCommand) -> None:
        self.notifications = notifications

    async def capture(self, intent: CheckoutIntentModel) -> None:
        kind = {
            "action_required": NotificationKind.CHECKOUT_ACTION_REQUIRED,
            "cancelled": NotificationKind.CHECKOUT_CANCELLED,
            "expired": NotificationKind.CHECKOUT_EXPIRED,
        }.get(intent.state)
        if kind is None:
            return
        await self.notifications.enqueue(
            intent.customer_id,
            NotificationEvent(
                event_key=f"checkout:{intent.id}:revision:{intent.revision}:{kind}",
                kind=kind,
                record_id=intent.id,
                amount_rial=intent.price_rial,
                status=intent.state,
            ),
        )


class CheckoutNoticeSourceQuery:
    def __init__(self, intents: CheckoutIntentRepository) -> None:
        self.intents = intents

    async def owned(
        self, customer_id: int, id: int
    ) -> CheckoutNoticeAction | None:
        source = await self.intents.owned_current(id, customer_id)
        if source is None:
            return None
        return CheckoutNoticeAction(checkout_id=source.id)
