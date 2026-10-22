"""Resolve native signed grants against current authoritative service records."""

from papilio_panel.modules.cores.interfaces import CoreCapability
from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.shared.errors import Missing
from papilio_panel.shared.operations import OperationStatus

from ..interfaces import ServiceStorage, SubscriptionOutput, SubscriptionTokens


class ServiceSubscriptions:
    def __init__(
        self,
        storage: ServiceStorage,
        tokens: SubscriptionTokens,
        access: AdminAccessCapability,
        cores: CoreCapability,
        output: SubscriptionOutput,
    ) -> None:
        self.storage = storage
        self.tokens = tokens
        self.access = access
        self.cores = cores
        self.output = output

    def render(self, token: str) -> bytes:
        grant = self.tokens.verify(token)
        service = self.storage.read_grant(grant)
        if service.status != OperationStatus.SUCCEEDED or not self.access.owner_permitted(
            service.owner_id
        ):
            raise Missing("The subscription is unavailable.")
        endpoint = self.cores.read_inbound(service.core_id, service.inbound_id, service.owner_id)
        credential = self.storage.credential(service.id, service.owner_id)
        body = self.output.render(service.name, endpoint, credential)
        return body
