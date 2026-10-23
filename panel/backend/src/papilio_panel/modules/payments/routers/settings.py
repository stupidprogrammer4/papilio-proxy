"""Owner payment-destination and evidence-limit controls."""

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..domain import PaymentDefinition, PaymentSettingsChange, PaymentSettingsCreate
from ..providers import payment_settings
from .principal import actor_id
from .schemas import (
    PaymentDefinitionSerializer,
    PaymentReplacementSerializer,
    PaymentSettingsSerializer,
)


class PaymentDefaultsView(APIView):
    @extend_schema(operation_id="read_payment_defaults", responses=PaymentDefinitionSerializer)
    def get(self, request: Request) -> Response:
        result = payment_settings.defaults(actor_id(request))
        return Response(PaymentDefinitionSerializer(result).data)


class PaymentSettingsView(APIView):
    @extend_schema(operation_id="read_payment_settings", responses=PaymentSettingsSerializer)
    def get(self, request: Request) -> Response:
        result = payment_settings.read(actor_id(request))
        return Response(PaymentSettingsSerializer(result).data)

    @extend_schema(
        operation_id="create_payment_settings",
        request=PaymentDefinitionSerializer,
        responses={201: PaymentSettingsSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = PaymentDefinitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        definition = PaymentDefinition(
            values["recipient"],
            values["destination"],
            values["instructions"],
            values["enabled"],
            values["receipt_max_bytes"],
        )
        result = payment_settings.create(PaymentSettingsCreate(actor_id(request), definition))
        return Response(PaymentSettingsSerializer(result).data, status=201)

    @extend_schema(
        operation_id="replace_payment_settings",
        request=PaymentReplacementSerializer,
        responses=PaymentSettingsSerializer,
    )
    def put(self, request: Request) -> Response:
        serializer = PaymentReplacementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        definition = PaymentDefinition(
            values["recipient"],
            values["destination"],
            values["instructions"],
            values["enabled"],
            values["receipt_max_bytes"],
        )
        result = payment_settings.change(
            PaymentSettingsChange(actor_id(request), int(values["expected_revision"]), definition)
        )
        return Response(PaymentSettingsSerializer(result).data)
