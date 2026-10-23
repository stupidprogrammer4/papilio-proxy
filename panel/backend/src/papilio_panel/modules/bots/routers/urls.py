"""Bot resource paths and nested administrative pairing ownership."""

from django.urls import path

from .bots import BotDefaultsView, BotPairingView, BotsView, BotView
from .shop import BotShopView, ShopDefaultsView

urlpatterns = [
    path("bot-shop-defaults", ShopDefaultsView.as_view()),
    path("bots/<uuid:bot_id>/shop", BotShopView.as_view()),
    path("bots/defaults", BotDefaultsView.as_view()),
    path("bots", BotsView.as_view()),
    path("bots/<uuid:bot_id>", BotView.as_view()),
    path("bots/<uuid:bot_id>/pairing", BotPairingView.as_view()),
]
