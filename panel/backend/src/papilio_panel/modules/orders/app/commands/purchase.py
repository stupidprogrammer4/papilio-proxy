"""One native DB transaction coordinates purchase, wallet and service outbox."""

from django.db import transaction

from papilio_panel.modules.catalog.interfaces import ProductCapability
from papilio_panel.modules.customers.interfaces import CustomerCapability
from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.modules.services.interfaces import ServiceCapability
from papilio_panel.modules.wallets.interfaces import WalletCapability

from ...domain import OrderCreation, PurchaseInput
from ...interfaces import OrderStorage
from ..terms import accepted_terms, definition, matching_request, native_service, wallet_posting


class OrderPurchase:
    def __init__(
        self,
        storage: OrderStorage,
        access: AdminAccessCapability,
        customers: CustomerCapability,
        products: ProductCapability,
        wallets: WalletCapability,
        services: ServiceCapability,
    ) -> None:
        self.storage = storage
        self.access = access
        self.customers = customers
        self.products = products
        self.wallets = wallets
        self.services = services

    @transaction.atomic
    def purchase(self, values: PurchaseInput) -> OrderCreation:
        self.access.authorize_owner(values.actor_id)
        definition(values.definition)
        self.customers.read(values.definition.customer_id, values.actor_id)
        prior = self.storage.find_request(values.actor_id, values.request_key)
        if prior is not None:
            matching_request(prior, values.definition)
            return OrderCreation(prior, False)
        product = self.products.read(values.definition.product_id, values.actor_id)
        reserved = self.storage.reserve(values, accepted_terms(product, values.definition))
        matching_request(reserved.order, values.definition)
        posting = wallet_posting(reserved.order, values.actor_id)
        entry_id = None
        if posting is not None:
            entry_id = self.wallets.post(posting).entry.id
        service = self.services.create(native_service(reserved.order, values.actor_id))
        result = self.storage.complete_purchase(
            reserved.order.id, values.actor_id, service.service.id, entry_id
        )
        return OrderCreation(result, reserved.created)
