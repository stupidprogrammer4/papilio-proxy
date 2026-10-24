"""Owner-authorized outgoing metadata and recovery, without exposing reply contents."""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from papilio_panel.modules.shop.domain import MessageState, RecoveryAction
from papilio_panel.modules.shop.providers import message_inspection, message_recovery
from papilio_panel.modules.shop.recovery_contracts import (
    InspectionWindow,
    MessageRecoveryInput,
    MessageSearch,
    RecoveryDefinition,
)

from .bots import actor_id
from .shop_recovery_schemas import (
    InspectionSearchSerializer,
    MessageInspectionSerializer,
    MessagePageSerializer,
    MessageRecoveryPageSerializer,
    MessageRecoveryResultSerializer,
    MessageSearchSerializer,
    RecoveryInputSerializer,
)


class ShopMessagesView(APIView):
    @extend_schema(
        operation_id="list_bot_shop_messages",
        parameters=[MessageSearchSerializer],
        responses=MessagePageSerializer,
    )
    def get(self, request: Request, bot_id: UUID) -> Response:
        serializer = MessageSearchSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = message_inspection.search(
            MessageSearch(
                actor_id(request),
                bot_id,
                values["q"],
                values["page"],
                values["page_size"],
                MessageState(values["status"]) if values["status"] else None,
            )
        )
        return Response(MessagePageSerializer(result).data)


class ShopMessageDetailView(APIView):
    @extend_schema(operation_id="read_bot_shop_message", responses=MessageInspectionSerializer)
    def get(self, request: Request, bot_id: UUID, message_id: UUID) -> Response:
        result = message_inspection.read(bot_id, message_id, actor_id(request))
        return Response(MessageInspectionSerializer(result).data)


class ShopMessageRecoveriesView(APIView):
    @extend_schema(
        operation_id="list_bot_message_recoveries",
        parameters=[InspectionSearchSerializer],
        responses=MessageRecoveryPageSerializer,
    )
    def get(self, request: Request, bot_id: UUID, message_id: UUID) -> Response:
        serializer = InspectionSearchSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = message_inspection.history(
            message_id,
            InspectionWindow(
                actor_id(request),
                bot_id,
                values["q"],
                values["page"],
                values["page_size"],
            ),
        )
        return Response(MessageRecoveryPageSerializer(result).data)

    @extend_schema(
        operation_id="create_bot_message_recovery",
        request=RecoveryInputSerializer,
        responses={201: MessageRecoveryResultSerializer, 200: MessageRecoveryResultSerializer},
    )
    def post(self, request: Request, bot_id: UUID, message_id: UUID) -> Response:
        serializer = RecoveryInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = message_recovery.recover(
            MessageRecoveryInput(
                actor_id(request),
                bot_id,
                message_id,
                RecoveryDefinition(
                    values["request_key"],
                    int(values["expected_revision"]),
                    RecoveryAction(values["action"]),
                    values["note"],
                ),
            )
        )
        return Response(
            MessageRecoveryResultSerializer(result).data, status=201 if result.created else 200
        )
