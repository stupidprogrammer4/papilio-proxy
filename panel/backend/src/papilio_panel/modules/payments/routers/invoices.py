"""Native issued invoice creation and scoped collections."""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..domain import InvoiceIssue, InvoiceSearch, InvoiceState
from ..providers import invoices
from .principal import actor_id
from .schemas import (
    InvoiceInputSerializer,
    InvoicePageSerializer,
    InvoiceSearchSerializer,
    InvoiceSerializer,
)


class InvoicesView(APIView):
    @extend_schema(
        operation_id="issue_invoice",
        request=InvoiceInputSerializer,
        responses={201: InvoiceSerializer, 200: InvoiceSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = InvoiceInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = invoices.issue(
            InvoiceIssue(
                actor_id(request),
                values["request_key"],
                values["customer_id"],
                values["base_amount_minor"],
            )
        )
        return Response(
            InvoiceSerializer(result.invoice).data, status=201 if result.created else 200
        )

    @extend_schema(
        operation_id="list_invoices",
        parameters=[InvoiceSearchSerializer],
        responses=InvoicePageSerializer,
    )
    def get(self, request: Request) -> Response:
        serializer = InvoiceSearchSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        state = InvoiceState(values["status"]) if values["status"] is not None else None
        result = invoices.search(
            InvoiceSearch(
                actor_id(request),
                values["customer_id"],
                state,
                values["page"],
                values["page_size"],
                values["q"],
            )
        )
        return Response(InvoicePageSerializer(result).data)


class InvoiceView(APIView):
    @extend_schema(operation_id="read_invoice", responses=InvoiceSerializer)
    def get(self, request: Request, invoice_id: UUID) -> Response:
        result = invoices.read(invoice_id, actor_id(request))
        return Response(InvoiceSerializer(result).data)
