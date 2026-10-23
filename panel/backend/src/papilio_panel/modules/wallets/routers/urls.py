"""Wallet-owned customer account relationships."""

from django.urls import path

from .wallets import CustomerWalletView, WalletEntriesView, WalletEntryView

urlpatterns = [
    path("customer-accounts/<uuid:customer_id>/wallet", CustomerWalletView.as_view()),
    path("customer-accounts/<uuid:customer_id>/wallet/entries", WalletEntriesView.as_view()),
    path(
        "customer-accounts/<uuid:customer_id>/wallet/entries/<uuid:entry_id>",
        WalletEntryView.as_view(),
    ),
]
