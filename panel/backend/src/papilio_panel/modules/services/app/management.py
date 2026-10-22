"""Persist immutable first service requests before external provisioning."""

from dataclasses import replace
from uuid import UUID

from django.db import transaction

from papilio_panel.modules.cores.interfaces import CoreCapability
from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.modules.nodes.interfaces import NodeCapability
from papilio_panel.shared.errors import Conflict, InvalidInput
from papilio_panel.shared.operations import OperationStatus

from ..domain import ServiceCreate, ServiceCreation, ServicePage, ServiceRead, ServiceSearch
from ..interfaces import ServiceStorage, SubscriptionTokens
from .validation import definition


class ServiceManagement:
    def __init__(
        self,
        storage: ServiceStorage,
        access: AdminAccessCapability,
        cores: CoreCapability,
        nodes: NodeCapability,
        tokens: SubscriptionTokens,
        max_page_size: int,
    ) -> None:
        self.storage = storage
        self.access = access
        self.cores = cores
        self.nodes = nodes
        self.tokens = tokens
        self.max_page_size = max_page_size

    @transaction.atomic
    def create(self, values: ServiceCreate) -> ServiceCreation:
        self.access.authorize_owner(values.actor_id)
        validated = replace(values, definition=definition(values.definition))
        selected = validated.definition
        core = self.cores.read(selected.core_id, values.actor_id)
        self.cores.read_inbound(core.id, selected.inbound_id, values.actor_id)
        node = self.nodes.read(core.node_id, values.actor_id)
        level = core.xray.default_user_level if selected.user_level is None else selected.user_level
        created = self.storage.create(
            validated, level, 3 * node.runtime.request_timeout_seconds + 10
        )
        if created.original_definition != selected:
            raise Conflict("This request key belongs to different service settings.")
        if created.created:
            self.storage.add_outbox(created.service.id)
        return created

    def read(self, service_id: UUID, actor_id: int) -> ServiceRead:
        self.access.authorize_owner(actor_id)
        service = self.storage.read(service_id, actor_id)
        self.cores.read_inbound(service.core_id, service.inbound_id, actor_id)
        return service

    def search(self, values: ServiceSearch) -> ServicePage:
        self.access.authorize_owner(values.actor_id)
        if values.page < 1 or not 1 <= values.page_size <= self.max_page_size:
            raise InvalidInput(
                "Choose a positive page and a page size within the configured limit."
            )
        page = self.storage.search(values)
        return page

    def subscription_token(self, service_id: UUID, actor_id: int) -> str:
        service = self.read(service_id, actor_id)
        if service.status != OperationStatus.SUCCEEDED:
            raise Conflict("Wait for successful native service provisioning.")
        grant = self.storage.subscription_grant(service_id, actor_id)
        token = self.tokens.issue(grant)
        return token
