"""Bind service ownership, native core control, delivery and subscription signing."""

from django.conf import settings

from papilio_panel.modules.cores.providers import cores
from papilio_panel.modules.identity.providers import admin_access
from papilio_panel.modules.nodes.providers import nodes, xray_control

from .app.execution import ServiceExecution
from .app.management import ServiceManagement
from .app.publications import ServicePublications
from .app.subscriptions import ServiceSubscriptions
from .infra.broker import NativeServicePublisher
from .infra.schedules import NativeServiceSchedule
from .infra.storage import DjangoServiceStorage
from .infra.subscription_output import VlessSubscriptionOutput
from .infra.tokens import NativeSubscriptionTokens
from .interfaces import (
    ServiceCapability,
    ServiceExecutionCapability,
    ServicePublicationCapability,
    ServiceSubscriptionCapability,
)

storage = DjangoServiceStorage()
tokens = NativeSubscriptionTokens()
services: ServiceCapability = ServiceManagement(
    storage, admin_access, cores, nodes, tokens, settings.PAPILIO_MAX_PAGE_SIZE
)
execution: ServiceExecutionCapability = ServiceExecution(storage, admin_access, cores, xray_control)
subscriptions: ServiceSubscriptionCapability = ServiceSubscriptions(
    storage, tokens, admin_access, cores, VlessSubscriptionOutput()
)
publications: ServicePublicationCapability = ServicePublications(
    storage, NativeServicePublisher(), NativeServiceSchedule()
)
