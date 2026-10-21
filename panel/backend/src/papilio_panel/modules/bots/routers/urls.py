"""Bot resource paths and nested administrative pairing ownership."""

from django.urls import path

from .bots import BotDefaultsView, BotPairingView, BotsView, BotView

urlpatterns = [
    path("bots/defaults", BotDefaultsView.as_view()),
    path("bots", BotsView.as_view()),
    path("bots/<uuid:bot_id>", BotView.as_view()),
    path("bots/<uuid:bot_id>/pairing", BotPairingView.as_view()),
]
