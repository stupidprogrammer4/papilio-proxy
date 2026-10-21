"""Typed diagnostic requests and owner-scoped operation resources."""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..domain import OperationRead, ProbeKind, ProbeSubmission
from ..providers import jobs


class ProbeInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[item.value for item in ProbeKind])
    request_key = serializers.UUIDField()


class ProbeResultSerializer(serializers.Serializer):
    worker_pid = serializers.IntegerField()
    worker_host = serializers.CharField()
    database_ok = serializers.BooleanField(allow_null=True)
    cache_ok = serializers.BooleanField(allow_null=True)
    digest = serializers.CharField(allow_null=True)


class OperationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    kind = serializers.CharField()
    status = serializers.CharField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    attempts = serializers.IntegerField()
    result = ProbeResultSerializer(allow_null=True)
    error_code = serializers.CharField(allow_null=True)
    status_url = serializers.SerializerMethodField()

    def get_status_url(self, operation: OperationRead) -> str:
        return f"/api/v1/system/operations/{operation.id}"


class ProbeView(APIView):
    serializer_class = ProbeInputSerializer

    @extend_schema(responses={202: OperationSerializer})
    def post(self, request: Request) -> Response:
        actor_id = request.user.pk
        if actor_id is None:
            raise NotAuthenticated()
        serializer = ProbeInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = ProbeSubmission(
            actor_id=actor_id,
            kind=ProbeKind(serializer.validated_data["kind"]),
            request_key=serializer.validated_data["request_key"],
        )
        operation = jobs.submit(values)
        return Response(OperationSerializer(operation).data, status=202)


class OperationView(APIView):
    serializer_class = OperationSerializer

    def get(self, request: Request, operation_id: UUID) -> Response:
        actor_id = request.user.pk
        if actor_id is None:
            raise NotAuthenticated()
        operation = jobs.read(operation_id, actor_id)
        return Response(OperationSerializer(operation).data)


class CancelOperationView(APIView):
    serializer_class = OperationSerializer

    @extend_schema(request=None, responses=OperationSerializer)
    def post(self, request: Request, operation_id: UUID) -> Response:
        actor_id = request.user.pk
        if actor_id is None:
            raise NotAuthenticated()
        operation = jobs.cancel(operation_id, actor_id)
        return Response(OperationSerializer(operation).data)
