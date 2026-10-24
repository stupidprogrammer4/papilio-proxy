"""Bot resource paths and nested administrative pairing ownership."""

from django.urls import path

from .bots import BotDefaultsView, BotPairingView, BotsView, BotView
from .shop import BotShopView, ShopDefaultsView
from .shop_messages import ShopMessageDetailView, ShopMessageRecoveriesView, ShopMessagesView
from .shop_work import ShopWorkDetailView, ShopWorkRecoveriesView, ShopWorkView

urlpatterns = [
    path("bot-shop-defaults", ShopDefaultsView.as_view()),
    path("bots/<uuid:bot_id>/shop", BotShopView.as_view()),
    path("bots/<uuid:bot_id>/shop/work", ShopWorkView.as_view()),
    path("bots/<uuid:bot_id>/shop/work/<uuid:work_id>", ShopWorkDetailView.as_view()),
    path(
        "bots/<uuid:bot_id>/shop/work/<uuid:work_id>/recoveries", ShopWorkRecoveriesView.as_view()
    ),
    path("bots/<uuid:bot_id>/shop/messages", ShopMessagesView.as_view()),
    path("bots/<uuid:bot_id>/shop/messages/<uuid:message_id>", ShopMessageDetailView.as_view()),
    path(
        "bots/<uuid:bot_id>/shop/messages/<uuid:message_id>/recoveries",
        ShopMessageRecoveriesView.as_view(),
    ),
    path("bots/defaults", BotDefaultsView.as_view()),
    path("bots", BotsView.as_view()),
    path("bots/<uuid:bot_id>", BotView.as_view()),
    path("bots/<uuid:bot_id>/pairing", BotPairingView.as_view()),
]
