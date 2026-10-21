"""Liveness and readiness report exercised execution boundaries."""

from dataclasses import asdict

from django.http import HttpRequest, JsonResponse
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..providers import execution_health


def liveness(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "alive"})


def readiness_view(request: HttpRequest) -> JsonResponse:
    facts = execution_health.readiness()
    ready = facts.database and facts.cache and facts.workers
    return JsonResponse(
        {"status": "ready" if ready else "not_ready", **asdict(facts)},
        status=200 if ready else 503,
    )


class WorkerObservationSerializer(serializers.Serializer):
    role = serializers.CharField()
    queue = serializers.CharField()
    worker_host = serializers.CharField()
    worker_pid = serializers.IntegerField()
    observed_at = serializers.DateTimeField()


class SystemStatusSerializer(serializers.Serializer):
    version = serializers.CharField()
    brand_title = serializers.CharField()
    environment = serializers.CharField()
    instance = serializers.CharField()
    database = serializers.BooleanField()
    cache = serializers.BooleanField()
    workers_ready = serializers.BooleanField()
    workers = WorkerObservationSerializer(many=True)
    available_modules = serializers.ListField(child=serializers.CharField())


class SystemStatusView(APIView):
    serializer_class = SystemStatusSerializer

    def get(self, request: Request) -> Response:
        status = execution_health.status()
        return Response(asdict(status))
