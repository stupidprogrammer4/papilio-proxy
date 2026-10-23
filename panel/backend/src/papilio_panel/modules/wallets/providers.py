"""Bind wallet accounting to native storage and customer permission contracts."""

from django.conf import settings

from papilio_panel.modules.customers.providers import customers
from papilio_panel.modules.identity.providers import admin_access

from .app.accounting import WalletAccounting
from .infra.storage import DjangoWalletStorage
from .interfaces import WalletCapability

wallets: WalletCapability = WalletAccounting(
    DjangoWalletStorage(), admin_access, customers, settings.PAPILIO_MAX_PAGE_SIZE
)
