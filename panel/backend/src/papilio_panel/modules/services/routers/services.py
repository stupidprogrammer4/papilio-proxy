"""Service-owned creation, reads and authorized subscription link adapters."""

from urllib.parse import urlencode
from uuid import UUID

from django.http import HttpResponse
from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..domain import ServiceCreate, ServiceDefinition, ServiceSearch, SubscriptionLink
from ..providers import services, subscriptions
from .schemas import (
    SearchSerializer,
    ServiceInputSerializer,
    ServicePageSerializer,
    ServiceSerializer,
    SubscriptionInputSerializer,
    SubscriptionLinkSerializer,
)


def actor_id(request: Request) -> int:
    identifier = request.user.pk
    if identifier is None:
        raise NotAuthenticated()
    return identifier


class ServicesView(APIView):
    serializer_class = ServiceInputSerializer

    @extend_schema(
        operation_id="list_services", parameters=[SearchSerializer], responses=ServicePageSerializer
    )
    def get(self, request: Request) -> Response:
        serializer = SearchSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        page = services.search(
            ServiceSearch(actor_id(request), values["q"], values["page"], values["page_size"])
        )
        return Response(ServicePageSerializer(page).data)

    @extend_schema(operation_id="create_service", responses={202: ServiceSerializer})
    def post(self, request: Request) -> Response:
        serializer = ServiceInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        creation = services.create(
            ServiceCreate(
                actor_id=actor_id(request),
                request_key=values["request_key"],
                definition=ServiceDefinition(
                    values["name"],
                    values["core_id"],
                    values["inbound_id"],
                    values["user_level"],
                    values["identifier"],
                ),
            )
        )
        return Response(ServiceSerializer(creation.service).data, status=202)


class ServiceView(APIView):
    serializer_class = ServiceSerializer

    @extend_schema(operation_id="read_service")
    def get(self, request: Request, service_id: UUID) -> Response:
        service = services.read(service_id, actor_id(request))
        return Response(ServiceSerializer(service).data)


class ServiceSubscriptionView(APIView):
    serializer_class = SubscriptionLinkSerializer

    @extend_schema(operation_id="read_service_subscription_link")
    def get(self, request: Request, service_id: UUID) -> Response:
        token = services.subscription_token(service_id, actor_id(request))
        origin = request.build_absolute_uri(reverse("service-subscription"))
        result = SubscriptionLink(f"{origin}?{urlencode({'token': token})}")
        response = Response(SubscriptionLinkSerializer(result).data)
        response["Cache-Control"] = "private, no-store"
        return response


class SubscriptionView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = SubscriptionInputSerializer

    @extend_schema(
        operation_id="read_subscription",
        parameters=[SubscriptionInputSerializer],
        responses={(200, "text/plain"): OpenApiTypes.BYTE},
    )
    def get(self, request: Request) -> HttpResponse:
        serializer = SubscriptionInputSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        body = subscriptions.render(serializer.validated_data["token"])
        response = HttpResponse(body, content_type="text/plain; charset=utf-8")
        response["Cache-Control"] = "private, no-store"
        return response
