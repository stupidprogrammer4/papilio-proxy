"""Bind the manual payment aggregate to native storage and public capabilities."""

from django.conf import settings

from papilio_panel.modules.customers.providers import customers
from papilio_panel.modules.identity.providers import admin_access
from papilio_panel.modules.wallets.providers import wallets

from .app.configuration import PaymentConfiguration
from .app.decision_history import PaymentDecisionHistory
from .app.decisions import ManualPaymentDecisions
from .app.invoices import InvoiceAccounts
from .app.receipts import ReceiptEvidence
from .infra.settings import DjangoPaymentSettingsStorage
from .infra.storage import DjangoInvoiceStorage
from .interfaces import (
    InvoiceCapability,
    PaymentDecisionCapability,
    PaymentDecisionHistoryCapability,
    PaymentSettingsCapability,
    ReceiptCapability,
)

payment_settings: PaymentSettingsCapability = PaymentConfiguration(
    DjangoPaymentSettingsStorage(), admin_access
)
_invoice_storage = DjangoInvoiceStorage()
invoices: InvoiceCapability = InvoiceAccounts(
    _invoice_storage,
    admin_access,
    customers,
    wallets,
    payment_settings,
    settings.PAPILIO_MAX_PAGE_SIZE,
)
receipts: ReceiptCapability = ReceiptEvidence(
    _invoice_storage, invoices, settings.PAPILIO_MAX_PAGE_SIZE
)
decisions: PaymentDecisionCapability = ManualPaymentDecisions(
    _invoice_storage, invoices, receipts, wallets
)
decision_history: PaymentDecisionHistoryCapability = PaymentDecisionHistory(
    _invoice_storage, invoices, settings.PAPILIO_MAX_PAGE_SIZE
)
