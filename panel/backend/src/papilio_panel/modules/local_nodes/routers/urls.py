"""Local runtime resource ownership and setup defaults."""

from django.urls import path

from .local_nodes import (
    LocalDefaultsView,
    LocalDeliveryView,
    LocalNodeView,
    LocalOperationsView,
    LocalOperationView,
)

urlpatterns = [
    path("setup/local-node", LocalDefaultsView.as_view()),
    path("system/local-node", LocalNodeView.as_view()),
    path("system/local-node/delivery", LocalDeliveryView.as_view()),
    path("system/local-node/operations", LocalOperationsView.as_view()),
    path("system/local-node/operations/<uuid:operation_id>", LocalOperationView.as_view()),
]
