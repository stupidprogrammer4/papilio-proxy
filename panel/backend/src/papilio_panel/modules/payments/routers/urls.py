"""Payment settings and invoice-owned receipt/audit resource paths."""

from django.urls import path

from .decisions import DecisionsView
from .invoices import InvoicesView, InvoiceView
from .receipts import ReceiptFileView, ReceiptsView, ReceiptView
from .settings import PaymentDefaultsView, PaymentSettingsView

urlpatterns = [
    path("payment-defaults", PaymentDefaultsView.as_view()),
    path("payment-settings", PaymentSettingsView.as_view()),
    path("invoices", InvoicesView.as_view()),
    path("invoices/<uuid:invoice_id>", InvoiceView.as_view()),
    path("invoices/<uuid:invoice_id>/receipts", ReceiptsView.as_view()),
    path("invoices/<uuid:invoice_id>/receipts/<uuid:receipt_id>", ReceiptView.as_view()),
    path("invoices/<uuid:invoice_id>/receipts/<uuid:receipt_id>/file", ReceiptFileView.as_view()),
    path("invoices/<uuid:invoice_id>/decisions", DecisionsView.as_view()),
]
