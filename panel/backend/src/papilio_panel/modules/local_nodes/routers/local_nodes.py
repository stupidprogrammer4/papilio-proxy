"""Native setup observations and owner-scoped local runtime resources."""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from ..domain import DeliveryPolicy, DeliveryUpdate, LocalCreate, LocalRetry
from ..providers import local_nodes, registration
from ..schemas import (
    DeliveryReadSerializer,
    DeliveryUpdateSerializer,
    LocalCreateSerializer,
    LocalDefaultsSerializer,
    LocalOperationSerializer,
    LocalReadSerializer,
    LocalRetrySerializer,
)


def actor_id(request: Request) -> int:
    identifier = request.user.pk
    if identifier is None:
        raise NotAuthenticated()
    return identifier


class LocalDefaultsView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    @extend_schema(operation_id="read_local_node_setup_defaults", responses=LocalDefaultsSerializer)
    def get(self, request: Request) -> Response:
        return Response(LocalDefaultsSerializer(local_nodes.defaults()).data)


class LocalNodeView(APIView):
    @extend_schema(operation_id="read_local_node", responses=LocalReadSerializer)
    def get(self, request: Request) -> Response:
        return Response(LocalReadSerializer(local_nodes.read(actor_id(request))).data)

    @extend_schema(
        operation_id="register_local_node",
        request=LocalCreateSerializer,
        responses={201: LocalReadSerializer, 200: LocalReadSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = LocalCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = registration.create(
            LocalCreate(
                actor_id(request),
                values["request_key"],
                values["definition"],
                values["delivery"],
            )
        )
        return Response(
            LocalReadSerializer(result.record).data, status=201 if result.created else 200
        )


class LocalDeliveryView(APIView):
    @extend_schema(
        operation_id="update_local_node_delivery",
        request=DeliveryUpdateSerializer,
        responses=DeliveryReadSerializer,
    )
    def put(self, request: Request) -> Response:
        serializer = DeliveryUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = local_nodes.update_delivery(
            DeliveryUpdate(
                actor_id(request),
                DeliveryPolicy(
                    values["enabled"], values["retry_interval_seconds"], values["max_attempts"]
                ),
                int(values["expected_revision"]),
            )
        )
        return Response(DeliveryReadSerializer(result).data)


class LocalOperationsView(APIView):
    @extend_schema(
        operation_id="retry_local_node_delivery",
        request=LocalRetrySerializer,
        responses={202: LocalOperationSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = LocalRetrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = local_nodes.retry(
            LocalRetry(actor_id(request), serializer.validated_data["request_key"])
        )
        return Response(LocalOperationSerializer(result).data, status=202)


class LocalOperationView(APIView):
    @extend_schema(operation_id="read_local_node_operation", responses=LocalOperationSerializer)
    def get(self, request: Request, operation_id: UUID) -> Response:
        result = local_nodes.read_operation(operation_id, actor_id(request))
        return Response(LocalOperationSerializer(result).data)
