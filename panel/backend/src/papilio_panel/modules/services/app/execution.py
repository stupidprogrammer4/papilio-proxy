"""Provision committed service requests through the scoped node capability."""

import math
from uuid import UUID

from django.utils import timezone

from papilio_panel.modules.cores.interfaces import CoreCapability
from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.modules.nodes.domain import VlessUser, XrayApply, XrayUserIdentity
from papilio_panel.modules.nodes.interfaces import NodeXrayControlCapability
from papilio_panel.shared.operations import OperationStatus

from ..domain import ServiceOutcome
from ..interfaces import ServiceStorage


class ServiceExecution:
    def __init__(
        self,
        storage: ServiceStorage,
        access: AdminAccessCapability,
        cores: CoreCapability,
        control: NodeXrayControlCapability,
    ) -> None:
        self.storage = storage
        self.access = access
        self.cores = cores
        self.control = control

    def provision(self, service_id: UUID) -> ServiceOutcome:
        claim = self.storage.claim(service_id)
        service = claim.service
        if claim.token is None:
            remaining = None
            if service.status == OperationStatus.RUNNING and service.lease_until:
                remaining = max(
                    1, math.ceil((service.lease_until - timezone.now()).total_seconds())
                )
            return ServiceOutcome(remaining)
        if not self.access.owner_permitted(service.owner_id):
            self.storage.finish(claim, "access_revoked")
            return ServiceOutcome()
        core = self.cores.read(service.core_id, service.owner_id)
        inbound = self.cores.read_inbound(core.id, service.inbound_id, service.owner_id)
        credential = self.storage.credential(service.id, service.owner_id)
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
        error_code = None if result.succeeded else result.error_code or "invalid_node_response"
        self.storage.finish(claim, error_code)
        return ServiceOutcome()
