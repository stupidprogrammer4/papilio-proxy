"""Bind service ownership, native core control, delivery and subscription signing."""

from django.conf import settings

from papilio_panel.modules.cores.providers import cores
from papilio_panel.modules.identity.providers import admin_access
from papilio_panel.modules.jobs.domain import ScheduleKind
from papilio_panel.modules.nodes.providers import nodes, xray_control

from .app.execution import ServiceExecution
from .app.management import ServiceManagement
from .app.publications import ServicePublications, ServiceSynchronizationPublications
from .app.subscriptions import ServiceSubscriptions
from .app.synchronization import ServiceSynchronizationExecution, ServiceSynchronizations
from .infra.broker import NativeServicePublisher, NativeServiceSynchronizationPublisher
from .infra.schedules import NativeServiceSchedule
from .infra.storage import DjangoServiceStorage
from .infra.subscription_output import VlessSubscriptionOutput
from .infra.synchronization import DjangoServiceSynchronizationStorage
from .infra.tokens import NativeSubscriptionTokens
from .interfaces import (
    ServiceCapability,
    ServiceExecutionCapability,
    ServicePublicationCapability,
    ServiceSubscriptionCapability,
)
from .synchronization_interfaces import (
    ServiceSynchronizationCapability,
    ServiceSynchronizationExecutionCapability,
    ServiceSynchronizationPublicationCapability,
)

storage = DjangoServiceStorage()
synchronization_storage = DjangoServiceSynchronizationStorage()
tokens = NativeSubscriptionTokens()
services: ServiceCapability = ServiceManagement(
    storage, admin_access, cores, nodes, tokens, settings.PAPILIO_MAX_PAGE_SIZE
)
synchronizations: ServiceSynchronizationCapability = ServiceSynchronizations(
    synchronization_storage, services
)
execution: ServiceExecutionCapability = ServiceExecution(storage, admin_access, cores, xray_control)
subscriptions: ServiceSubscriptionCapability = ServiceSubscriptions(
    storage, tokens, admin_access, cores, VlessSubscriptionOutput()
)
publications: ServicePublicationCapability = ServicePublications(
    storage, NativeServicePublisher(), NativeServiceSchedule()
)
_synchronization_schedule = NativeServiceSchedule(ScheduleKind.SERVICE_SYNCHRONIZATION)
synchronization_execution: ServiceSynchronizationExecutionCapability = (
    ServiceSynchronizationExecution(
        synchronization_storage,
        storage,
        admin_access,
        cores,
        xray_control,
        _synchronization_schedule,
    )
)
synchronization_publications: ServiceSynchronizationPublicationCapability = (
    ServiceSynchronizationPublications(
        synchronization_storage, NativeServiceSynchronizationPublisher(), _synchronization_schedule
    )
)
