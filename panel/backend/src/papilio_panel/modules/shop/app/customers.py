"""Resolve verified private senders into shared customer/wallet identities atomically."""

from django.db import transaction

from papilio_panel.modules.bots.interfaces import BotConversationCapability
from papilio_panel.modules.customers.domain import CustomerCreate
from papilio_panel.modules.customers.interfaces import CustomerCapability
from papilio_panel.modules.wallets.domain import WalletOpen
from papilio_panel.modules.wallets.interfaces import WalletCapability
from papilio_panel.shared.errors import Conflict, Missing
from papilio_panel.shared.money import Currency

from ..domain import ShopCustomerContext
from ..interfaces import CustomerBindingStorage, ShopControlCapability


class ShopCustomerRegistration:
    def __init__(
        self,
        storage: CustomerBindingStorage,
        events: BotConversationCapability,
        settings: ShopControlCapability,
        customers: CustomerCapability,
        wallets: WalletCapability,
    ) -> None:
        self.storage = storage
        self.events = events
        self.settings = settings
        self.customers = customers
        self.wallets = wallets

    @transaction.atomic
    def register(self, event_id: int) -> ShopCustomerContext:
        event = self.events.event(event_id)
        if event.message is None:
            raise Missing("The event has no verified private Telegram sender.")
        settings = self.settings.read(event.bot.id, event.bot.owner_id)
        if (
            not settings.definition.enabled
            or not event.bot.schedule.enabled
            or not event.bot.verified
        ):
            raise Conflict("The bot shop is paused or its identity is not verified.")
        reserved = self.storage.reserve(event.bot.owner_id, event.message.sender_id)
        if reserved.created:
            name = event.message.name.strip()[:80].rstrip() or str(event.message.sender_id)
            made = self.customers.create(
                CustomerCreate(event.bot.owner_id, reserved.binding.id, name)
            )
            self.wallets.open(WalletOpen(event.bot.owner_id, made.customer.id, Currency.IRR))
            self.storage.bind(reserved.binding.id, event.bot.owner_id, made.customer.id)
            return ShopCustomerContext(event, settings, made.customer)
        if reserved.binding.customer_id is None:
            raise Missing("The Telegram identity is missing its persisted customer account.")
        customer = self.customers.read(reserved.binding.customer_id, event.bot.owner_id)
        self.wallets.read(customer.id, event.bot.owner_id)
        return ShopCustomerContext(event, settings, customer)
