"""Customer-scoped purchase history and actual service subscription readiness."""

from urllib.parse import urlencode
from uuid import UUID

from papilio_panel.modules.bots.domain import TelegramButton, TelegramReply
from papilio_panel.modules.orders.domain import OrderSearch
from papilio_panel.modules.orders.interfaces import OrderReadCapability
from papilio_panel.modules.services.interfaces import ServiceCapability
from papilio_panel.shared.errors import Conflict, Missing
from papilio_panel.shared.operations import OperationStatus

from ..domain import ShopCustomerContext, ShopTextContext
from .presentation import menu, render, reply


class ShopOrderQueries:
    def __init__(self, orders: OrderReadCapability, services: ServiceCapability) -> None:
        self.orders = orders
        self.services = services

    def search(self, context: ShopCustomerContext, page: int) -> TelegramReply:
        settings = context.settings.definition
        orders = self.orders.search(
            OrderSearch(
                context.customer.owner_id,
                customer_id=context.customer.id,
                page=page,
                page_size=settings.page_size,
            )
        )
        buttons = tuple(
            TelegramButton(
                f"{order.terms.product_name} · {order.terms.price_minor} IRR",
                f"order:{order.id.hex}",
            )
            for order in orders.items
        )
        if page > 1:
            buttons += (TelegramButton(render(settings, "previous_button"), f"orders:{page - 1}"),)
        if page * settings.page_size < orders.count:
            buttons += (TelegramButton(render(settings, "next_button"), f"orders:{page + 1}"),)
        heading = render(settings, "orders", ShopTextContext(page=str(page)))
        if not orders.items:
            heading += "\n" + render(settings, "empty")
        return TelegramReply(heading, buttons + menu(settings))

    def read(self, context: ShopCustomerContext, order_id: UUID) -> TelegramReply:
        order = self.orders.read(order_id, context.customer.owner_id)
        if order.customer_id != context.customer.id:
            raise Missing("The order was not found in this customer chat.")
        if order.service_id is None:
            raise Conflict("The purchase has no committed service yet.")
        service = self.services.read(order.service_id, context.customer.owner_id)
        settings = context.settings.definition
        text = ShopTextContext(
            order_id=str(order.id),
            amount=str(order.terms.price_minor),
            status=service.status.value,
        )
        if service.status == OperationStatus.SUCCEEDED:
            token = self.services.subscription_token(service.id, context.customer.owner_id)
            url = (
                settings.public_origin.rstrip("/")
                + "/api/v1/subscriptions?"
                + urlencode({"token": token})
            )
            return reply(settings, "subscription", ShopTextContext(url=url, order_id=str(order.id)))
        return TelegramReply(
            render(settings, "order", text),
            (TelegramButton(render(settings, "status_button"), f"order:{order.id.hex}"),)
            + menu(settings),
        )
