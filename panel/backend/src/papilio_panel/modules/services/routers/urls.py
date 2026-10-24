"""Persistent service resources and signed public subscription delivery."""

from django.urls import path

from .services import ServiceSubscriptionView, ServicesView, ServiceView, SubscriptionView
from .synchronization import ServiceSynchronizationView

urlpatterns = [
    path("services", ServicesView.as_view()),
    path("services/<uuid:service_id>", ServiceView.as_view()),
    path("services/<uuid:service_id>/synchronization", ServiceSynchronizationView.as_view()),
    path("services/<uuid:service_id>/subscription", ServiceSubscriptionView.as_view()),
    path("subscriptions", SubscriptionView.as_view(), name="service-subscription"),
]
