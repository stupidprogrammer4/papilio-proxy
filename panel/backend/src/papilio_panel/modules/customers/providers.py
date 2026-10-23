"""Bind native customer accounts for API and commerce consumers."""

from django.conf import settings

from papilio_panel.modules.identity.providers import admin_access

from .app.accounts import CustomerAccounts
from .infra.storage import DjangoCustomerStorage
from .interfaces import CustomerCapability

customers: CustomerCapability = CustomerAccounts(
    DjangoCustomerStorage(), admin_access, settings.PAPILIO_MAX_PAGE_SIZE
)
