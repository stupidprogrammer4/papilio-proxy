"""Bind purchase commands and order reads to native module capabilities."""

from django.conf import settings

from papilio_panel.modules.catalog.providers import products
from papilio_panel.modules.customers.providers import customers
from papilio_panel.modules.identity.providers import admin_access
from papilio_panel.modules.services.providers import services
from papilio_panel.modules.wallets.providers import wallets

from .app.commands.purchase import OrderPurchase
from .app.queries import OrderQueries
from .infra.storage import DjangoOrderStorage
from .interfaces import OrderPurchaseCapability, OrderReadCapability

_order_storage = DjangoOrderStorage()
purchases: OrderPurchaseCapability = OrderPurchase(
    _order_storage, admin_access, customers, products, wallets, services
)
orders: OrderReadCapability = OrderQueries(
    _order_storage, admin_access, customers, settings.PAPILIO_MAX_PAGE_SIZE
)
