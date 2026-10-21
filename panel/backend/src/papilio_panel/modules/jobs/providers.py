"""Bind the operation aggregate and worker implementations."""

from django.conf import settings

from papilio_panel.modules.identity.providers import admin_access

from .app.execution import ProbeExecution
from .app.health import ExecutionHealth
from .app.publications import OperationPublications
from .app.requests import JobRequests
from .app.schedules import ManagedSchedules
from .infra.broker import CeleryDeliveryPublisher
from .infra.health import DjangoExecutionHealthStorage
from .infra.operations import DjangoOperationStorage
from .infra.probes import NativeProbeChecks
from .infra.schedules import DjangoScheduleStorage
from .interfaces import (
    ExecutionHealthCapability,
    JobCapability,
    ProbeExecutionCapability,
    PublicationCapability,
    ScheduleCapability,
)

operation_storage = DjangoOperationStorage()
managed_schedules: ScheduleCapability = ManagedSchedules(DjangoScheduleStorage(), admin_access)
jobs: JobCapability = JobRequests(operation_storage, admin_access)
probe_execution: ProbeExecutionCapability = ProbeExecution(
    operation_storage, NativeProbeChecks(), admin_access
)

publications: PublicationCapability = OperationPublications(
    operation_storage, CeleryDeliveryPublisher()
)
execution_health: ExecutionHealthCapability = ExecutionHealth(
    DjangoExecutionHealthStorage(),
    settings.PAPILIO_ENV,
    settings.PAPILIO_INSTANCE,
    settings.PAPILIO_BRAND_TITLE,
)
