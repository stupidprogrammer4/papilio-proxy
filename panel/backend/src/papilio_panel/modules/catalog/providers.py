"""Bind the catalogue to native aggregates and authoritative core contracts."""

from django.conf import settings

from papilio_panel.modules.cores.providers import cores
from papilio_panel.modules.identity.providers import admin_access

from .app.products import ProductCatalog
from .infra.storage import DjangoProductStorage
from .interfaces import ProductCapability

products: ProductCapability = ProductCatalog(
    DjangoProductStorage(), admin_access, cores, settings.PAPILIO_MAX_PAGE_SIZE
)
