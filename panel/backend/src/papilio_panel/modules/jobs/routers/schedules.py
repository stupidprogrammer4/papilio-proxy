"""Edit managed intervals through typed, owner-scoped inputs."""

from dataclasses import asdict

from django.contrib.auth.models import User
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotAuthenticated, NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..domain import ScheduleKind, ScheduleUpdate
from ..providers import managed_schedules


class ScheduleSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    interval_seconds = serializers.IntegerField(min_value=1, max_value=2147483647)
    expected_changed_at = serializers.DateTimeField()


class ScheduleReadSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=[key.value for key in ScheduleKind])
    enabled = serializers.BooleanField()
    interval_seconds = serializers.IntegerField(min_value=1, max_value=2147483647)
    changed_at = serializers.DateTimeField()


class SchedulesView(APIView):
    serializer_class = ScheduleReadSerializer

    @extend_schema(responses=ScheduleReadSerializer(many=True))
    def get(self, request: Request) -> Response:
        user = request.user
        if not isinstance(user, User) or user.pk is None:
            raise NotAuthenticated()
        rows = managed_schedules.read_all(user.pk)
        return Response([asdict(row) for row in rows])


class ScheduleView(APIView):
    serializer_class = ScheduleSerializer

    @extend_schema(responses=ScheduleReadSerializer)
    def put(self, request: Request, schedule_key: str) -> Response:
        user = request.user
        if not isinstance(user, User) or user.pk is None:
            raise NotAuthenticated()
        try:
            key = ScheduleKind(schedule_key)
        except ValueError as error:
            raise NotFound("This schedule is not managed by Papilio.") from error
        serializer = ScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = ScheduleUpdate(
            key=key,
            enabled=serializer.validated_data["enabled"],
            interval_seconds=serializer.validated_data["interval_seconds"],
            expected_changed_at=serializer.validated_data["expected_changed_at"],
        )
        result = managed_schedules.update(user.pk, values)
        return Response(asdict(result))
