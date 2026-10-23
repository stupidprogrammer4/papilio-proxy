"""Wallet resource reads and explicitly privileged journal posting."""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from papilio_panel.shared.money import Currency

from ..domain import EntryKind, JournalInput, JournalSearch, WalletChange, WalletOpen, WalletPost
from ..providers import wallets
from .schemas import (
    JournalInputSerializer,
    JournalPageSerializer,
    JournalSerializer,
    SearchSerializer,
    WalletChangeSerializer,
    WalletOpenSerializer,
    WalletSerializer,
)


def actor_id(request: Request) -> int:
    identifier = request.user.pk
    if identifier is None:
        raise NotAuthenticated()
    return identifier


class CustomerWalletView(APIView):
    @extend_schema(operation_id="read_customer_wallet", responses=WalletSerializer)
    def get(self, request: Request, customer_id: UUID) -> Response:
        result = wallets.read(customer_id, actor_id(request))
        return Response(WalletSerializer(result).data)

    @extend_schema(
        operation_id="open_customer_wallet",
        request=WalletOpenSerializer,
        responses={201: WalletSerializer, 200: WalletSerializer},
    )
    def post(self, request: Request, customer_id: UUID) -> Response:
        serializer = WalletOpenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = wallets.open(
            WalletOpen(
                actor_id(request),
                customer_id,
                Currency(values["currency"]),
                values["credit_limit_minor"],
            )
        )
        return Response(WalletSerializer(result.wallet).data, status=201 if result.created else 200)

    @extend_schema(
        operation_id="change_customer_wallet_settings",
        request=WalletChangeSerializer,
        responses=WalletSerializer,
    )
    def put(self, request: Request, customer_id: UUID) -> Response:
        serializer = WalletChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = wallets.change(
            WalletChange(
                actor_id(request),
                customer_id,
                int(values["expected_revision"]),
                values["credit_limit_minor"],
            )
        )
        return Response(WalletSerializer(result).data)


class WalletEntriesView(APIView):
    @extend_schema(
        operation_id="list_wallet_entries",
        parameters=[SearchSerializer],
        responses=JournalPageSerializer,
    )
    def get(self, request: Request, customer_id: UUID) -> Response:
        serializer = SearchSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = wallets.search(
            JournalSearch(
                actor_id(request), customer_id, values["q"], values["page"], values["page_size"]
            )
        )
        return Response(JournalPageSerializer(result).data)

    @extend_schema(
        operation_id="post_wallet_entry",
        request=JournalInputSerializer,
        responses={201: JournalSerializer, 200: JournalSerializer},
    )
    def post(self, request: Request, customer_id: UUID) -> Response:
        serializer = JournalInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = wallets.post(
            WalletPost(
                actor_id(request),
                customer_id,
                JournalInput(
                    values["request_key"],
                    EntryKind(values["kind"]),
                    values["amount_minor"],
                    values["reason"],
                ),
            )
        )
        return Response(JournalSerializer(result.entry).data, status=201 if result.created else 200)


class WalletEntryView(APIView):
    @extend_schema(operation_id="read_wallet_entry", responses=JournalSerializer)
    def get(self, request: Request, customer_id: UUID, entry_id: UUID) -> Response:
        result = wallets.read_entry(entry_id, customer_id, actor_id(request))
        return Response(JournalSerializer(result).data)
