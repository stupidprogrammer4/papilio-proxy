"""Read shared catalogue and wallet contracts for a verified shop customer."""

from rest_framework import serializers

from papilio_panel.modules.bots.domain import TelegramButton, TelegramReply
from papilio_panel.modules.catalog.domain import ProductSearch
from papilio_panel.modules.catalog.interfaces import ProductCapability
from papilio_panel.modules.wallets.interfaces import WalletCapability

from ..domain import ShopCustomerContext, ShopTextContext
from ..interfaces import ShopOrderQueryCapability
from .presentation import menu, render, reply


class ShopMenus:
    def __init__(
        self,
        products: ProductCapability,
        wallets: WalletCapability,
        orders: ShopOrderQueryCapability,
    ) -> None:
        self.products = products
        self.wallets = wallets
        self.orders = orders

    def response(self, context: ShopCustomerContext) -> TelegramReply:
        message = context.event.message
        command = (message.callback_data or message.text).strip() if message else ""
        settings = context.settings.definition
        if command in {"/start", "menu"}:
            result = reply(settings, "welcome", ShopTextContext(name=context.customer.name))
        elif command in {"/wallet", "wallet"}:
            wallet = self.wallets.read(context.customer.id, context.customer.owner_id)
            result = reply(settings, "wallet", ShopTextContext(balance=str(wallet.balance_minor)))
        elif command in {"/catalogue", "/catalog", "/products"} or command.startswith("catalogue:"):
            _, _, argument = command.partition(":")
            page = serializers.IntegerField(min_value=1).run_validation(argument or "1")
            result = self.catalogue(context, page)
        elif command.startswith("order:"):
            _, _, argument = command.partition(":")
            order_id = serializers.UUIDField().run_validation(argument)
            result = self.orders.read(context, order_id)
        elif command == "/orders" or command.startswith("orders:"):
            _, _, argument = command.partition(":")
            page = serializers.IntegerField(min_value=1).run_validation(argument or "1")
            result = self.orders.search(context, page)
        else:
            result = reply(settings, "help")
        return result

    def catalogue(self, context: ShopCustomerContext, page: int) -> TelegramReply:
        settings = context.settings.definition
        products = self.products.search(
            ProductSearch(
                context.customer.owner_id, page=page, page_size=settings.page_size, active_only=True
            )
        )
        buttons = tuple(
            TelegramButton(
                f"{item.offer.definition.name} · {item.offer.definition.price_minor} IRR",
                f"offer:{item.id.hex}",
            )
            for item in products.items
        )
        if page > 1:
            buttons += (
                TelegramButton(render(settings, "previous_button"), f"catalogue:{page - 1}"),
            )
        if page * settings.page_size < products.count:
            buttons += (TelegramButton(render(settings, "next_button"), f"catalogue:{page + 1}"),)
        heading = render(settings, "catalogue", ShopTextContext(page=str(page)))
        if not products.items:
            heading += "\n" + render(settings, "empty")
        return TelegramReply(heading, buttons + menu(settings))
