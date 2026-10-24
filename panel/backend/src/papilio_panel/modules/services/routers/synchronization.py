"""Owner-scoped synchronization policy and last native observation."""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..providers import synchronizations
from ..synchronization_contracts import SynchronizationUpdate
from .services import actor_id


class SynchronizationInputSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    interval_seconds = serializers.IntegerField(min_value=1, max_value=2147483647)
    expected_revision = serializers.RegexField(r"^[1-9][0-9]{0,18}$", max_length=19)


class SynchronizationSerializer(serializers.Serializer):
    service_id = serializers.UUIDField()
    enabled = serializers.BooleanField()
    interval_seconds = serializers.IntegerField()
    revision = serializers.CharField()
    generation = serializers.CharField()
    status = serializers.CharField()
    attempts = serializers.CharField()
    error_code = serializers.CharField(allow_null=True)
    worker_pid = serializers.IntegerField(allow_null=True)
    lease_until = serializers.DateTimeField(allow_null=True)
    due_at = serializers.DateTimeField()
    last_completed_at = serializers.DateTimeField(allow_null=True)


class ServiceSynchronizationView(APIView):
    @extend_schema(operation_id="read_service_synchronization", responses=SynchronizationSerializer)
    def get(self, request: Request, service_id: UUID) -> Response:
        result = synchronizations.read(service_id, actor_id(request))
        return Response(SynchronizationSerializer(result).data)

    @extend_schema(
        operation_id="update_service_synchronization",
        request=SynchronizationInputSerializer,
        responses=SynchronizationSerializer,
    )
    def put(self, request: Request, service_id: UUID) -> Response:
        serializer = SynchronizationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = synchronizations.update(
            SynchronizationUpdate(
                actor_id(request),
                service_id,
                values["enabled"],
                values["interval_seconds"],
                int(values["expected_revision"]),
            )
        )
        return Response(SynchronizationSerializer(result).data)
