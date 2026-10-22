"""Bind registered-core capabilities to native persistence and scoped owners."""

from django.conf import settings

from papilio_panel.modules.identity.providers import admin_access
from papilio_panel.modules.nodes.providers import nodes

from .app.registration import CoreRegistration
from .infra.storage import DjangoCoreStorage
from .interfaces import CoreCapability

cores: CoreCapability = CoreRegistration(
    DjangoCoreStorage(), admin_access, nodes, settings.PAPILIO_MAX_PAGE_SIZE
)
