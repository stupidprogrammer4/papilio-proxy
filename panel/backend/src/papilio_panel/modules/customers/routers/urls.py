"""Customer account resource paths."""

from django.urls import path

from .accounts import CustomerAccountsView, CustomerAccountView

urlpatterns = [
    path("customer-accounts", CustomerAccountsView.as_view()),
    path("customer-accounts/<uuid:customer_id>", CustomerAccountView.as_view()),
]
