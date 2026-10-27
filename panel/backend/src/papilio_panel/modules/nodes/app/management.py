"""Permission-scoped node onboarding and operation requests."""

from dataclasses import replace
from uuid import UUID

from django.db import transaction

from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.shared.errors import Conflict, InvalidInput

from ..domain import (
    NodeConfigurationUpdate,
    NodeCreate,
    NodeCreation,
    NodeDefaults,
    NodePage,
    NodeRead,
    NodeSearch,
    NodeWorkKind,
    NodeWorkRead,
    WorkSubmission,
)
from ..interfaces import BootstrapArchive, NodeStorage
from .validation import validated_configuration, validated_definition


class NodeManagement:
    def __init__(
        self, storage: NodeStorage, access: AdminAccessCapability, archive: BootstrapArchive
    ) -> None:
        self.storage = storage
        self.access = access
        self.archive = archive

    def defaults(self, actor_id: int) -> NodeDefaults:
        self.access.authorize_owner(actor_id)
        return NodeDefaults()

    @transaction.atomic
    def create(self, values: NodeCreate) -> NodeCreation:
        self.access.authorize_owner(values.actor_id)
        validated = replace(values, definition=validated_definition(values.definition))
        creation = self.storage.create(validated)
        if (
            creation.operation.node_id != creation.node.id
            or creation.operation.kind != NodeWorkKind.ISSUE
        ):
            raise Conflict("This request key belongs to another node operation.")
        if creation.original_definition != validated.definition:
            raise Conflict("This request key belongs to different node settings.")
        if creation.created:
            self.storage.add_outbox(creation.operation.id)
        return creation

    def read(self, node_id: UUID, actor_id: int) -> NodeRead:
        self.access.authorize_owner(actor_id)
        node = self.storage.read(node_id, actor_id)
        return node

    @transaction.atomic
    def update_configuration(self, values: NodeConfigurationUpdate) -> NodeRead:
        self.access.authorize_owner(values.actor_id)
        if values.expected_revision < 1:
            raise InvalidInput("Choose a positive node configuration revision.")
        validated_configuration(values.runtime, values.certificate_policy)
        node = self.storage.update_configuration(values)
        return node

    def search(self, values: NodeSearch) -> NodePage:
        self.access.authorize_owner(values.actor_id)
        if not 1 <= values.page_size <= 200 or values.page < 1:
            raise InvalidInput("Choose a positive page and page size from 1 to 200.")
        result = self.storage.search(values)
        return result

    @transaction.atomic
    def submit(self, values: WorkSubmission) -> NodeWorkRead:
        self.read(values.node_id, values.actor_id)
        creation = self.storage.create_work(values)
        if creation.operation.node_id != values.node_id or creation.operation.kind != values.kind:
            raise Conflict("This request key belongs to another node operation.")
        if creation.created:
            self.storage.add_outbox(creation.operation.id)
        return creation.operation

    def read_work(self, node_id: UUID, operation_id: UUID, actor_id: int) -> NodeWorkRead:
        self.read(node_id, actor_id)
        operation = self.storage.read_work(node_id, operation_id, actor_id)
        return operation

    def bootstrap(self, node_id: UUID, actor_id: int) -> bytes:
        node = self.read(node_id, actor_id)
        if not node.credentials_ready:
            raise Conflict("Wait for the credential operation to finish.")
        credentials = self.storage.credentials(node_id, actor_id)
        archive = self.archive.build(node, credentials)
        return archive
