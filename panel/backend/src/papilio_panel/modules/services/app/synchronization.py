"""Owner policy and scoped desired-state synchronization without financial replay."""

from uuid import UUID

from django.db import transaction

from papilio_panel.modules.cores.interfaces import CoreCapability
from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.modules.nodes.domain import VlessUser, XrayApply, XrayUserIdentity
from papilio_panel.modules.nodes.interfaces import NodeXrayControlCapability

from ..interfaces import ServiceCapability, ServiceDeliverySchedule, ServiceStorage
from ..synchronization_contracts import (
    SynchronizationClaim,
    SynchronizationRead,
    SynchronizationUpdate,
)
from ..synchronization_interfaces import ServiceSynchronizationStorage
from .validation import synchronization_policy


class ServiceSynchronizations:
    def __init__(self, storage: ServiceSynchronizationStorage, services: ServiceCapability) -> None:
        self.storage = storage
        self.services = services

    def read(self, service_id: UUID, actor_id: int) -> SynchronizationRead:
        self.services.read(service_id, actor_id)
        return self.storage.read(service_id, actor_id)

    @transaction.atomic
    def update(self, values: SynchronizationUpdate) -> SynchronizationRead:
        self.services.read(values.service_id, values.actor_id)
        synchronization_policy(values)
        return self.storage.update(values)


class ServiceSynchronizationExecution:
    def __init__(
        self,
        storage: ServiceSynchronizationStorage,
        services: ServiceStorage,
        access: AdminAccessCapability,
        cores: CoreCapability,
        control: NodeXrayControlCapability,
        schedule: ServiceDeliverySchedule,
    ) -> None:
        self.storage = storage
        self.services = services
        self.access = access
        self.cores = cores
        self.control = control
        self.schedule = schedule

    def begin(self, service_id: UUID, generation: int) -> SynchronizationClaim | None:
        if not self.schedule.enabled():
            return None
        claim = self.storage.claim(service_id, generation)
        if claim is not None and not self.access.owner_permitted(claim.service.owner_id):
            self.storage.finish(claim, "access_revoked")
            return None
        return claim

    def apply(self, claim: SynchronizationClaim) -> None:
        service = claim.service
        core = self.cores.read(service.core_id, service.owner_id)
        inbound = self.cores.read_inbound(core.id, service.inbound_id, service.owner_id)
        credential = self.services.credential(service.id, service.owner_id)
        if not self.storage.active(claim):
            return
        result = self.control.apply(
            XrayApply(
                service.owner_id,
                core.node_id,
                VlessUser(
                    XrayUserIdentity(inbound.tag, credential.email),
                    credential.identifier,
                    level=credential.level,
                ),
            )
        )
        self.storage.finish(
            claim, None if result.succeeded else result.error_code or "invalid_node_response"
        )

    def reject(self, claim: SynchronizationClaim, error_code: str) -> None:
        self.storage.finish(claim, error_code)
