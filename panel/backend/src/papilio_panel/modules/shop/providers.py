"""Bind native shop policy to current bot and owner interfaces."""

from django.conf import settings

from papilio_panel.modules.bots.providers import bots, conversations
from papilio_panel.modules.catalog.providers import products
from papilio_panel.modules.customers.providers import customers
from papilio_panel.modules.identity.providers import admin_access
from papilio_panel.modules.orders.providers import orders, purchases
from papilio_panel.modules.payments.providers import invoices, payment_events, receipts
from papilio_panel.modules.services.providers import services
from papilio_panel.modules.wallets.providers import wallets

from .app.configuration import ShopConfiguration
from .app.customers import ShopCustomerQueries, ShopCustomerRegistration
from .app.execution import ShopExecution
from .app.funding import ShopFunding
from .app.invoices import ShopInvoiceQueries
from .app.menus import ShopMenus
from .app.orders import ShopOrderQueries
from .app.publications import ShopPublications
from .app.purchases import ShopPurchases
from .app.receipt_preparation import ShopReceiptPreparation
from .app.sending import ShopSending
from .app.settlements import ShopSettlementNotifications
from .infra.broker import NativeShopPublisher
from .infra.customers import DjangoCustomerBindingStorage
from .infra.invoices import DjangoInvoiceOriginStorage
from .infra.messages import DjangoShopMessageStorage
from .infra.purchases import DjangoPurchaseConfirmationStorage
from .infra.schedules import NativeShopSchedule
from .infra.settings import DjangoShopSettingsStorage
from .infra.work import DjangoShopWorkStorage
from .interfaces import (
    ShopControlCapability,
    ShopCustomerCapability,
    ShopCustomerQueryCapability,
    ShopExecutionCapability,
    ShopFundingCapability,
    ShopInvoiceQueryCapability,
    ShopMenuCapability,
    ShopOrderQueryCapability,
    ShopPublicationCapability,
    ShopPurchaseCapability,
    ShopReceiptPreparationCapability,
    ShopSendingCapability,
    ShopSettlementCapability,
)

control: ShopControlCapability = ShopConfiguration(
    DjangoShopSettingsStorage(), admin_access, bots, settings.PAPILIO_MAX_PAGE_SIZE
)
shop_customers: ShopCustomerCapability = ShopCustomerRegistration(
    DjangoCustomerBindingStorage(), conversations, control, customers, wallets
)
shop_customer_queries: ShopCustomerQueryCapability = ShopCustomerQueries(
    DjangoCustomerBindingStorage(), conversations, control, customers
)
_work = DjangoShopWorkStorage()
_messages = DjangoShopMessageStorage()
_schedule = NativeShopSchedule()
shop_orders: ShopOrderQueryCapability = ShopOrderQueries(orders, services)
shop_invoices: ShopInvoiceQueryCapability = ShopInvoiceQueries(invoices, _messages)
menus: ShopMenuCapability = ShopMenus(products, wallets, shop_orders, shop_invoices)
_origins = DjangoInvoiceOriginStorage()
funding: ShopFundingCapability = ShopFunding(invoices, receipts, shop_invoices, _origins, _messages)
receipt_preparation: ShopReceiptPreparationCapability = ShopReceiptPreparation(
    conversations, shop_customer_queries, shop_invoices
)
shop_purchases: ShopPurchaseCapability = ShopPurchases(
    DjangoPurchaseConfirmationStorage(), products, purchases, orders
)
execution: ShopExecutionCapability = ShopExecution(
    _work,
    _messages,
    conversations,
    control,
    shop_customers,
    menus,
    _schedule,
    shop_purchases,
    funding,
    receipt_preparation,
)
sending: ShopSendingCapability = ShopSending(_messages, conversations, control, _schedule)
settlements: ShopSettlementCapability = ShopSettlementNotifications(
    payment_events, invoices, _origins, shop_customer_queries, _messages
)
publications: ShopPublicationCapability = ShopPublications(
    _work, _messages, NativeShopPublisher(), _schedule, payment_events
)
