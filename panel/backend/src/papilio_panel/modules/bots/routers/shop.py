"""Owner-only sales settings within their existing bot resource context."""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from papilio_panel.modules.shop.domain import ShopDefinition, ShopSettingsChange, ShopSettingsCreate
from papilio_panel.modules.shop.providers import control

from .bots import actor_id
from .shop_schemas import (
    ShopDefinitionSerializer,
    ShopReplacementSerializer,
    ShopSettingsSerializer,
)


class ShopDefaultsView(APIView):
    @extend_schema(operation_id="read_bot_shop_defaults", responses=ShopDefinitionSerializer)
    def get(self, request: Request) -> Response:
        result = control.defaults(actor_id(request))
        return Response(ShopDefinitionSerializer(result).data)


class BotShopView(APIView):
    @extend_schema(operation_id="read_bot_shop", responses=ShopSettingsSerializer)
    def get(self, request: Request, bot_id: UUID) -> Response:
        result = control.read(bot_id, actor_id(request))
        return Response(ShopSettingsSerializer(result).data)

    @extend_schema(
        operation_id="create_bot_shop",
        request=ShopDefinitionSerializer,
        responses={201: ShopSettingsSerializer},
    )
    def post(self, request: Request, bot_id: UUID) -> Response:
        serializer = ShopDefinitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        definition = ShopDefinition(
            values["public_origin"],
            values["enabled"],
            values["delivery_enabled"],
            values["locale"],
            values["page_size"],
            values["retry_seconds"],
            values["lease_seconds"],
            values["max_attempts"],
            values["confirmation_ttl_seconds"],
            values["ambiguous_delivery"],
            values["texts"],
        )
        result = control.create(ShopSettingsCreate(actor_id(request), bot_id, definition))
        return Response(ShopSettingsSerializer(result).data, status=201)

    @extend_schema(
        operation_id="replace_bot_shop",
        request=ShopReplacementSerializer,
        responses=ShopSettingsSerializer,
    )
    def put(self, request: Request, bot_id: UUID) -> Response:
        serializer = ShopReplacementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        definition = ShopDefinition(
            values["public_origin"],
            values["enabled"],
            values["delivery_enabled"],
            values["locale"],
            values["page_size"],
            values["retry_seconds"],
            values["lease_seconds"],
            values["max_attempts"],
            values["confirmation_ttl_seconds"],
            values["ambiguous_delivery"],
            values["texts"],
        )
        result = control.change(
            ShopSettingsChange(
                actor_id(request), bot_id, int(values["expected_revision"]), definition
            )
        )
        return Response(ShopSettingsSerializer(result).data)
