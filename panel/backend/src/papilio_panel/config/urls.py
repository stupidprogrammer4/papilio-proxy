"""Public transport composition only."""

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

from papilio_panel.modules.jobs.routers.health import liveness, readiness_view

urlpatterns = [
    path("api/v1/", include("papilio_panel.modules.identity.routers.urls")),
    path("api/v1/", include("papilio_panel.modules.jobs.routers.urls")),
    path("api/v1/", include("papilio_panel.modules.nodes.routers.urls")),
    path("api/v1/", include("papilio_panel.modules.local_nodes.routers.urls")),
    path("api/v1/", include("papilio_panel.modules.bots.routers.urls")),
    path("api/v1/", include("papilio_panel.modules.cores.routers.urls")),
    path("api/v1/", include("papilio_panel.modules.services.routers.urls")),
    path("api/v1/", include("papilio_panel.modules.customers.routers.urls")),
    path("api/v1/", include("papilio_panel.modules.wallets.routers.urls")),
    path("api/v1/", include("papilio_panel.modules.catalog.routers.urls")),
    path("api/v1/", include("papilio_panel.modules.orders.routers.urls")),
    path("api/v1/", include("papilio_panel.modules.payments.routers.urls")),
    path("health/live", liveness),
    path("health/ready", readiness_view),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
]
