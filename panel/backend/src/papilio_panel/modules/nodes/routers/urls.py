"""Node resource ownership at the HTTP boundary."""

from django.urls import path

from .nodes import (
    NodeBootstrapView,
    NodeDefaultsView,
    NodeOperationsView,
    NodeOperationView,
    NodesView,
    NodeView,
)

urlpatterns = [
    path("nodes/defaults", NodeDefaultsView.as_view()),
    path("nodes", NodesView.as_view()),
    path("nodes/<uuid:node_id>", NodeView.as_view()),
    path("nodes/<uuid:node_id>/operations", NodeOperationsView.as_view()),
    path("nodes/<uuid:node_id>/operations/<uuid:operation_id>", NodeOperationView.as_view()),
    path("nodes/<uuid:node_id>/bootstrap", NodeBootstrapView.as_view()),
]
