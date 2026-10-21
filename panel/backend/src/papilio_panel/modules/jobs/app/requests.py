"""Owner-scoped asynchronous request orchestration."""

from uuid import UUID

from django.db import transaction

from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.shared.errors import Conflict
from papilio_panel.shared.operations import OperationStatus

from ..domain import OperationRead, ProbeSubmission
from ..interfaces import OperationStorage


class JobRequests:
    def __init__(self, storage: OperationStorage, access: AdminAccessCapability) -> None:
        self.storage = storage
        self.access = access

    @transaction.atomic
    def submit(self, values: ProbeSubmission) -> OperationRead:
        self.access.authorize_actor(values.actor_id)
        creation = self.storage.create(values)
        if creation.operation.kind != values.kind:
            raise Conflict("This request key already belongs to different inputs.")
        if creation.created:
            self.storage.add_outbox(creation.operation.id)
        return creation.operation

    def read(self, operation_id: UUID, actor_id: int) -> OperationRead:
        self.access.authorize_actor(actor_id)
        operation = self.storage.read(operation_id, actor_id)
        return operation

    @transaction.atomic
    def cancel(self, operation_id: UUID, actor_id: int) -> OperationRead:
        self.access.authorize_actor(actor_id)
        self.storage.cancel_queued(operation_id, actor_id)
        operation = self.storage.read(operation_id, actor_id)
        if operation.status != OperationStatus.CANCELLED:
            raise Conflict("Only a queued operation can be cancelled.")
        return operation
