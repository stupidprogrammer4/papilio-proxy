"""Audited manual approvals and rejections through the native application path."""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..domain import DecisionAction, DecisionInput, DecisionSearch
from ..providers import decision_history, decisions
from .principal import actor_id
from .schemas import (
    DecisionInputSerializer,
    DecisionPageSerializer,
    DecisionResultSerializer,
    PageSearchSerializer,
)


class DecisionsView(APIView):
    @extend_schema(
        operation_id="decide_invoice_payment",
        request=DecisionInputSerializer,
        responses={201: DecisionResultSerializer, 200: DecisionResultSerializer},
    )
    def post(self, request: Request, invoice_id: UUID) -> Response:
        serializer = DecisionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = decisions.decide(
            DecisionInput(
                actor_id(request),
                invoice_id,
                values["request_key"],
                int(values["expected_revision"]),
                DecisionAction(values["action"]),
                values["reason"],
                values["receipt_id"],
            )
        )
        return Response(
            DecisionResultSerializer(result).data, status=201 if result.created else 200
        )

    @extend_schema(
        operation_id="list_invoice_decisions",
        parameters=[PageSearchSerializer],
        responses=DecisionPageSerializer,
    )
    def get(self, request: Request, invoice_id: UUID) -> Response:
        serializer = PageSearchSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = decision_history.search(
            DecisionSearch(
                actor_id(request), invoice_id, values["page"], values["page_size"], values["q"]
            )
        )
        return Response(DecisionPageSerializer(result).data)
