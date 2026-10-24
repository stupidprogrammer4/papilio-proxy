"""Owner-authorized incoming work and its explicit recovery resources."""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from papilio_panel.modules.shop.domain import RecoveryAction, WorkState
from papilio_panel.modules.shop.providers import work_inspection, work_recovery
from papilio_panel.modules.shop.recovery_contracts import (
    InspectionWindow,
    RecoveryDefinition,
    WorkRecoveryInput,
    WorkSearch,
)

from .bots import actor_id
from .shop_recovery_schemas import (
    InspectionSearchSerializer,
    RecoveryInputSerializer,
    WorkInspectionSerializer,
    WorkPageSerializer,
    WorkRecoveryPageSerializer,
    WorkRecoveryResultSerializer,
    WorkSearchSerializer,
)


class ShopWorkView(APIView):
    @extend_schema(
        operation_id="list_bot_shop_work",
        parameters=[WorkSearchSerializer],
        responses=WorkPageSerializer,
    )
    def get(self, request: Request, bot_id: UUID) -> Response:
        serializer = WorkSearchSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = work_inspection.search(
            WorkSearch(
                actor_id(request),
                bot_id,
                values["q"],
                values["page"],
                values["page_size"],
                WorkState(values["status"]) if values["status"] else None,
            )
        )
        return Response(WorkPageSerializer(result).data)


class ShopWorkDetailView(APIView):
    @extend_schema(operation_id="read_bot_shop_work", responses=WorkInspectionSerializer)
    def get(self, request: Request, bot_id: UUID, work_id: UUID) -> Response:
        result = work_inspection.read(bot_id, work_id, actor_id(request))
        return Response(WorkInspectionSerializer(result).data)


class ShopWorkRecoveriesView(APIView):
    @extend_schema(
        operation_id="list_bot_work_recoveries",
        parameters=[InspectionSearchSerializer],
        responses=WorkRecoveryPageSerializer,
    )
    def get(self, request: Request, bot_id: UUID, work_id: UUID) -> Response:
        serializer = InspectionSearchSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = work_inspection.history(
            work_id,
            InspectionWindow(
                actor_id(request),
                bot_id,
                values["q"],
                values["page"],
                values["page_size"],
            ),
        )
        return Response(WorkRecoveryPageSerializer(result).data)

    @extend_schema(
        operation_id="create_bot_work_recovery",
        request=RecoveryInputSerializer,
        responses={201: WorkRecoveryResultSerializer, 200: WorkRecoveryResultSerializer},
    )
    def post(self, request: Request, bot_id: UUID, work_id: UUID) -> Response:
        serializer = RecoveryInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = work_recovery.recover(
            WorkRecoveryInput(
                actor_id(request),
                bot_id,
                work_id,
                RecoveryDefinition(
                    values["request_key"],
                    int(values["expected_revision"]),
                    RecoveryAction(values["action"]),
                    values["note"],
                ),
            )
        )
        return Response(
            WorkRecoveryResultSerializer(result).data, status=201 if result.created else 200
        )
