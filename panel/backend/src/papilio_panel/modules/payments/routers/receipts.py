"""Multipart evidence intake and private authenticated attachment download."""

from uuid import UUID

from django.core.files.uploadedfile import UploadedFile
from django.http import HttpResponse
from django.utils.http import content_disposition_header
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..domain import ReceiptContent, ReceiptSearch, ReceiptSubmit
from ..providers import invoices, receipts
from .principal import actor_id
from .schemas import (
    PageSearchSerializer,
    ReceiptInputSerializer,
    ReceiptPageSerializer,
    ReceiptSerializer,
)


class ReceiptsView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        operation_id="submit_invoice_receipt",
        request=ReceiptInputSerializer,
        responses={201: ReceiptSerializer, 200: ReceiptSerializer},
    )
    def post(self, request: Request, invoice_id: UUID) -> Response:
        actor = actor_id(request)
        invoice = invoices.read(invoice_id, actor)
        serializer = ReceiptInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        upload = values.get("file")
        attachment = None
        if isinstance(upload, UploadedFile):
            attachment = ReceiptContent(
                upload.name or "receipt",
                upload.content_type or "application/octet-stream",
                upload.read(invoice.settings.receipt_max_bytes + 1),
            )
        result = receipts.submit(
            ReceiptSubmit(
                actor,
                invoice_id,
                values["request_key"],
                values["reference"],
                values["note"],
                attachment,
            )
        )
        return Response(
            ReceiptSerializer(result.receipt).data, status=201 if result.created else 200
        )

    @extend_schema(
        operation_id="list_invoice_receipts",
        parameters=[PageSearchSerializer],
        responses=ReceiptPageSerializer,
    )
    def get(self, request: Request, invoice_id: UUID) -> Response:
        serializer = PageSearchSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = receipts.search(
            ReceiptSearch(
                actor_id(request), invoice_id, values["page"], values["page_size"], values["q"]
            )
        )
        return Response(ReceiptPageSerializer(result).data)


class ReceiptView(APIView):
    @extend_schema(operation_id="read_invoice_receipt", responses=ReceiptSerializer)
    def get(self, request: Request, invoice_id: UUID, receipt_id: UUID) -> Response:
        result = receipts.read(receipt_id, invoice_id, actor_id(request))
        return Response(ReceiptSerializer(result).data)


class ReceiptFileView(APIView):
    @extend_schema(
        operation_id="download_invoice_receipt",
        responses={(200, "application/octet-stream"): OpenApiTypes.BINARY},
    )
    def get(self, request: Request, invoice_id: UUID, receipt_id: UUID) -> HttpResponse:
        result = receipts.file(receipt_id, invoice_id, actor_id(request))
        response = HttpResponse(result.data, content_type="application/octet-stream")
        response["Content-Disposition"] = (
            content_disposition_header(True, result.filename) or "attachment"
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
