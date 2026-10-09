from src.modules.operations.notifications.interfaces import (
    INotificationDeliveryCommand,
    INotificationTransport,
)


class NotificationDeliveryHandler:
    def __init__(
        self,
        command: INotificationDeliveryCommand,
        transport: INotificationTransport,
    ) -> None:
        self.command, self.transport = command, transport

    async def deliver(self, id: int) -> bool:
        claim = await self.command.claim(id)
        if claim is None:
            return False
        outcome = await self.transport.send(claim)
        result = await self.command.finish(id, claim.claim_token, outcome)
        return result
