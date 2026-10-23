"""Accepted order resource paths."""

from django.urls import path

from .orders import OrdersView, OrderView

urlpatterns = [
    path("orders", OrdersView.as_view()),
    path("orders/<uuid:order_id>", OrderView.as_view()),
]
