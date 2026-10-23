"""Confirm an immutable quoted offer using the shared wallet purchase contract."""

from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from papilio_panel.modules.bots.domain import TelegramButton, TelegramReply
from papilio_panel.modules.catalog.interfaces import ProductCapability
from papilio_panel.modules.orders.domain import OrderRead, PurchaseDefinition, PurchaseInput
from papilio_panel.modules.orders.interfaces import OrderPurchaseCapability, OrderReadCapability
from papilio_panel.shared.errors import Conflict, Missing

from ..domain import PurchaseConfirmation, ShopCustomerContext, ShopTextContext
from ..interfaces import PurchaseConfirmationStorage
from .presentation import menu, render


def purchase_reply(context: ShopCustomerContext, order: OrderRead) -> TelegramReply:
    if order.customer_id != context.customer.id:
        raise Missing("The order was not found in this customer chat.")
    settings = context.settings.definition
    text = render(
        settings,
        "queued",
        ShopTextContext(order_id=str(order.id), amount=str(order.terms.price_minor)),
    )
    return TelegramReply(
        text,
        (TelegramButton(render(settings, "status_button"), f"order:{order.id.hex}"),)
        + menu(settings),
    )


class ShopPurchases:
    def __init__(
        self,
        storage: PurchaseConfirmationStorage,
        products: ProductCapability,
        purchases: OrderPurchaseCapability,
        orders: OrderReadCapability,
    ) -> None:
        self.storage = storage
        self.products = products
        self.purchases = purchases
        self.orders = orders

    @transaction.atomic
    def select(
        self, context: ShopCustomerContext, work_id: UUID, product_id: UUID
    ) -> TelegramReply:
        product = self.products.read(product_id, context.customer.owner_id)
        offer = product.offer
        if not offer.definition.is_active:
            raise Conflict("This product is no longer available.")
        settings = context.settings.definition
        confirmation = self.storage.reserve(
            PurchaseConfirmation(
                work_id,
                context.event.bot.id,
                context.customer.id,
                product.id,
                offer.revision,
                offer.definition.name,
                timezone.now() + timedelta(seconds=settings.confirmation_ttl_seconds),
                None,
            )
        )
        text = render(
            settings,
            "offer",
            ShopTextContext(
                product=offer.definition.name, amount=str(offer.definition.price_minor)
            ),
        )
        return TelegramReply(
            text,
            (TelegramButton(render(settings, "buy_button"), f"buy:{confirmation.id.hex}"),)
            + menu(settings),
        )

    @transaction.atomic
    def confirm(self, context: ShopCustomerContext, confirmation_id: UUID) -> TelegramReply:
        confirmation = self.storage.read(confirmation_id, context.event.bot.id, context.customer.id)
        if confirmation.order_id is not None:
            order = self.orders.read(confirmation.order_id, context.customer.owner_id)
            return purchase_reply(context, order)
        if confirmation.expires_at <= timezone.now():
            raise Conflict(
                "This confirmation expired. Select the product again to review its price."
            )
        result = self.purchases.purchase(
            PurchaseInput(
                context.customer.owner_id,
                confirmation.id,
                PurchaseDefinition(
                    context.customer.id,
                    confirmation.product_id,
                    confirmation.offer_revision,
                    confirmation.service_name,
                ),
            )
        )
        self.storage.complete(confirmation, result.order.id)
        return purchase_reply(context, result.order)
