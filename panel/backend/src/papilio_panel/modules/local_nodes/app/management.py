"""Scoped local runtime reads and independent delivery policy/retry operations."""

from uuid import UUID

from django.db import transaction

from papilio_panel.modules.cores.interfaces import CoreCapability
from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.modules.nodes.interfaces import NodeCapability
from papilio_panel.shared.errors import InvalidInput, Missing

from ..domain import (
    DeliveryRead,
    DeliveryUpdate,
    LocalDefaults,
    LocalOperationRead,
    LocalRead,
    LocalRetry,
)
from ..interfaces import LocalConfiguration, LocalStorage
from .validation import binding, delivery_policy


class LocalNodeManagement:
    def __init__(
        self,
        storage: LocalStorage,
        access: AdminAccessCapability,
        nodes: NodeCapability,
        cores: CoreCapability,
        configuration: LocalConfiguration,
    ) -> None:
        self.storage, self.access = storage, access
        self.nodes, self.cores, self.configuration = nodes, cores, configuration

    def defaults(self) -> LocalDefaults:
        return self.configuration.defaults()

    def read(self, actor_id: int) -> LocalRead:
        self.access.authorize_owner(actor_id)
        record = self.storage.current(actor_id)
        if record is None:
            raise Missing("The local node was not found.")
        node = self.nodes.read(record.node_id, actor_id)
        core = self.cores.read(record.core_id, actor_id)
        inbound = self.cores.read_inbound(core.id, record.inbound_id, actor_id)
        binding(record, node, core, inbound)
        return record

    @transaction.atomic
    def update_delivery(self, values: DeliveryUpdate) -> DeliveryRead:
        self.read(values.actor_id)
        delivery_policy(values.policy)
        if (
            type(values.expected_revision) is not int
            or not 1 <= values.expected_revision < 9223372036854775807
        ):
            raise InvalidInput("Choose the current delivery settings revision.")
        return self.storage.update_delivery(values)

    @transaction.atomic
    def retry(self, values: LocalRetry) -> LocalOperationRead:
        self.read(values.actor_id)
        return self.storage.retry(values)

    def read_operation(self, operation_id: UUID, actor_id: int) -> LocalOperationRead:
        self.read(actor_id)
        return self.storage.read_operation(operation_id, actor_id)
