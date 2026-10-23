"""Native customer creation and complete authorized reads."""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..domain import CustomerCreate, CustomerSearch
from ..providers import customers


class CustomerInputSerializer(serializers.Serializer):
    request_key = serializers.UUIDField()
    name = serializers.CharField(max_length=80)


class CustomerSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    owner_id = serializers.IntegerField()
    name = serializers.CharField()


class SearchSerializer(serializers.Serializer):
    q = serializers.CharField(default="", allow_blank=True)
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, default=20)


class CustomerPageSerializer(serializers.Serializer):
    items = CustomerSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()


def actor_id(request: Request) -> int:
    identifier = request.user.pk
    if identifier is None:
        raise NotAuthenticated()
    return identifier


class CustomerAccountsView(APIView):
    @extend_schema(
        operation_id="list_customer_accounts",
        parameters=[SearchSerializer],
        responses=CustomerPageSerializer,
    )
    def get(self, request: Request) -> Response:
        serializer = SearchSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = customers.search(
            CustomerSearch(actor_id(request), values["q"], values["page"], values["page_size"])
        )
        return Response(CustomerPageSerializer(result).data)

    @extend_schema(
        operation_id="create_customer_account",
        request=CustomerInputSerializer,
        responses={201: CustomerSerializer, 200: CustomerSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = CustomerInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = customers.create(
            CustomerCreate(actor_id(request), values["request_key"], values["name"])
        )
        return Response(
            CustomerSerializer(result.customer).data, status=201 if result.created else 200
        )


class CustomerAccountView(APIView):
    @extend_schema(operation_id="read_customer_account", responses=CustomerSerializer)
    def get(self, request: Request, customer_id: UUID) -> Response:
        result = customers.read(customer_id, actor_id(request))
        return Response(CustomerSerializer(result).data)
