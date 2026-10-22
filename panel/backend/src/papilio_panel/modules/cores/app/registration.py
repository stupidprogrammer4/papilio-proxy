"""Owner-scoped registration of existing native cores and client endpoints."""

from dataclasses import replace
from uuid import UUID

from django.db import transaction

from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.modules.nodes.interfaces import NodeCapability
from papilio_panel.shared.errors import Conflict

from ..domain import (
    CoreCreation,
    CorePage,
    CoreRead,
    CoreSearch,
    InboundCreation,
    InboundPage,
    InboundSearch,
    XrayInboundRead,
    XrayInboundRegistration,
    XrayRegistration,
)
from ..interfaces import CoreStorage
from .validation import inbound_definition, registration, validate_window


class CoreRegistration:
    def __init__(
        self,
        storage: CoreStorage,
        access: AdminAccessCapability,
        nodes: NodeCapability,
        max_page_size: int,
    ) -> None:
        self.storage = storage
        self.access = access
        self.nodes = nodes
        self.max_page_size = max_page_size

    @transaction.atomic
    def register_xray(self, values: XrayRegistration) -> CoreCreation:
        self.access.authorize_owner(values.actor_id)
        validated = registration(values)
        self.nodes.read(validated.node_id, validated.actor_id)
        creation = self.storage.register_xray(validated)
        current = creation.core
        if (
            current.node_id != validated.node_id
            or current.name != validated.name
            or current.xray != validated.xray
        ):
            raise Conflict("This request key belongs to different core settings.")
        return creation

    def read(self, core_id: UUID, actor_id: int) -> CoreRead:
        self.access.authorize_owner(actor_id)
        core = self.storage.read(core_id, actor_id)
        self.nodes.read(core.node_id, actor_id)
        return core

    def search(self, values: CoreSearch) -> CorePage:
        self.access.authorize_owner(values.actor_id)
        validate_window(values.page, values.page_size, self.max_page_size)
        result = self.storage.search(values)
        return result

    @transaction.atomic
    def register_inbound(self, values: XrayInboundRegistration) -> InboundCreation:
        self.read(values.core_id, values.actor_id)
        validated = replace(values, definition=inbound_definition(values.definition))
        creation = self.storage.register_inbound(validated)
        current, expected = creation.inbound, validated.definition
        if (
            current.tag != expected.tag
            or current.public_host != expected.public_host
            or current.port != expected.port
        ):
            raise Conflict("This request key belongs to different inbound settings.")
        return creation

    def read_inbound(self, core_id: UUID, inbound_id: UUID, actor_id: int) -> XrayInboundRead:
        self.read(core_id, actor_id)
        inbound = self.storage.read_inbound(core_id, inbound_id, actor_id)
        return inbound

    def search_inbounds(self, values: InboundSearch) -> InboundPage:
        self.read(values.core_id, values.actor_id)
        validate_window(values.page, values.page_size, self.max_page_size)
        result = self.storage.search_inbounds(values)
        return result
