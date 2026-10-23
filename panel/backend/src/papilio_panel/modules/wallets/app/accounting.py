"""Authorize and apply exact journal postings in native Django transactions."""

from uuid import UUID

from django.db import transaction

from papilio_panel.modules.customers.interfaces import CustomerCapability
from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.shared.errors import Conflict, InvalidInput

from ..domain import (
    JournalEntryCreation,
    JournalEntryRead,
    JournalPage,
    JournalSearch,
    WalletChange,
    WalletOpen,
    WalletOpening,
    WalletPost,
    WalletRead,
)
from ..interfaces import WalletStorage
from .amounts import balance_change, credit_limit, entry, observed_balance, opening


class WalletAccounting:
    def __init__(
        self,
        storage: WalletStorage,
        access: AdminAccessCapability,
        customers: CustomerCapability,
        max_page_size: int,
    ) -> None:
        self.storage = storage
        self.access = access
        self.customers = customers
        self.max_page_size = max_page_size

    @transaction.atomic
    def open(self, values: WalletOpen) -> WalletOpening:
        self.access.authorize_owner(values.actor_id)
        self.customers.read(values.customer_id, values.actor_id)
        opening(values)
        result = self.storage.open(values)
        if (
            result.wallet.currency != values.currency
            or result.wallet.credit_limit_minor != values.credit_limit_minor
        ):
            raise Conflict("This customer already has a wallet with different settings.")
        return result

    def read(self, customer_id: UUID, actor_id: int) -> WalletRead:
        self.access.authorize_owner(actor_id)
        self.customers.read(customer_id, actor_id)
        result = self.storage.read(customer_id, actor_id)
        return result

    @transaction.atomic
    def post(self, values: WalletPost) -> JournalEntryCreation:
        wallet = self.read(values.customer_id, values.actor_id)
        entry(values.entry)
        reserved = self.storage.reserve(wallet.id, values.actor_id, values.entry)
        if reserved.original != values.entry:
            raise Conflict("This journal request key belongs to different posting details.")
        if reserved.created:
            change = balance_change(wallet, values.entry)
            balance = self.storage.change_balance(change, values.actor_id)
            self.storage.complete_entry(reserved.id, observed_balance(balance, change))
        result = self.storage.read_entry(reserved.id, values.customer_id, values.actor_id)
        return JournalEntryCreation(result, reserved.created)

    @transaction.atomic
    def change(self, values: WalletChange) -> WalletRead:
        wallet = self.read(values.customer_id, values.actor_id)
        credit_limit(values.credit_limit_minor)
        if (
            type(values.expected_revision) is not int
            or not 1 <= values.expected_revision < 9223372036854775807
        ):
            raise InvalidInput("Choose a positive wallet configuration revision.")
        result = self.storage.change(wallet.id, values, -values.credit_limit_minor)
        return result

    def read_entry(self, entry_id: UUID, customer_id: UUID, actor_id: int) -> JournalEntryRead:
        self.read(customer_id, actor_id)
        result = self.storage.read_entry(entry_id, customer_id, actor_id)
        return result

    def search(self, values: JournalSearch) -> JournalPage:
        self.read(values.customer_id, values.actor_id)
        if values.page < 1 or not 1 <= values.page_size <= self.max_page_size:
            raise InvalidInput("Choose a positive page and a supported page size.")
        result = self.storage.search(values)
        return result
