"""Atomically register the bundled node/core/inbound and durable local work."""

from django.db import transaction

from papilio_panel.modules.cores.domain import (
    XrayInboundDefinition,
    XrayInboundRegistration,
    XrayRegistration,
    XraySettings,
)
from papilio_panel.modules.cores.interfaces import CoreCapability
from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.modules.nodes.domain import NodeCreate
from papilio_panel.modules.nodes.interfaces import NodeCapability
from papilio_panel.shared.errors import Conflict, InvalidInput

from ..domain import LocalBinding, LocalCreate, LocalCreation
from ..interfaces import LocalNodeCapability, LocalStorage
from .validation import definition, delivery_policy, same_request


class LocalNodeRegistration:
    def __init__(
        self,
        storage: LocalStorage,
        access: AdminAccessCapability,
        nodes: NodeCapability,
        cores: CoreCapability,
        management: LocalNodeCapability,
    ) -> None:
        self.storage, self.access = storage, access
        self.nodes, self.cores, self.management = nodes, cores, management

    @transaction.atomic
    def create(self, values: LocalCreate) -> LocalCreation:
        self.access.authorize_owner(values.actor_id)
        defaults = self.management.defaults()
        if not defaults.available:
            raise InvalidInput("This installation has no bundled local runtime configured.")
        definition(values.definition)
        delivery_policy(values.delivery)
        existing = self.storage.current(values.actor_id)
        if existing is not None:
            same_request(existing, values)
            return LocalCreation(self.management.read(values.actor_id), False)
        return self._register(values)

    def _register(self, values: LocalCreate) -> LocalCreation:
        selected = values.definition
        node = self.nodes.create(NodeCreate(values.actor_id, values.request_key, selected.node))
        core = self.cores.register_xray(
            XrayRegistration(
                values.actor_id,
                values.request_key,
                node.node.id,
                selected.core_name,
                XraySettings(selected.default_user_level),
            )
        )
        inbound = self.cores.register_inbound(
            XrayInboundRegistration(
                values.actor_id,
                core.core.id,
                values.request_key,
                XrayInboundDefinition(
                    selected.inbound_tag, selected.public_host, selected.public_port
                ),
            )
        )
        creation = self.storage.create(
            LocalBinding(
                values,
                node.node.id,
                node.operation.id,
                core.core.id,
                inbound.inbound.id,
                3 * node.node.runtime.request_timeout_seconds + 10,
            )
        )
        same_request(creation.record, values)
        if (
            creation.record.node_id != node.node.id
            or creation.record.core_id != core.core.id
            or creation.record.inbound_id != inbound.inbound.id
        ):
            raise Conflict("The bundled runtime was registered by another request.")
        return creation
