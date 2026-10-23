"""Native authenticated purchase commands and authorized order reads."""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..domain import OrderSearch, PurchaseDefinition, PurchaseInput
from ..providers import orders, purchases
from .schemas import OrderPageSerializer, OrderSerializer, PurchaseInputSerializer, SearchSerializer


def actor_id(request: Request) -> int:
    identifier = request.user.pk
    if identifier is None:
        raise NotAuthenticated()
    return identifier


class OrdersView(APIView):
    @extend_schema(
        operation_id="list_orders", parameters=[SearchSerializer], responses=OrderPageSerializer
    )
    def get(self, request: Request) -> Response:
        serializer = SearchSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = orders.search(
            OrderSearch(
                actor_id(request),
                values["customer_id"],
                values["q"],
                values["page"],
                values["page_size"],
            )
        )
        return Response(OrderPageSerializer(result).data)

    @extend_schema(
        operation_id="purchase_order",
        request=PurchaseInputSerializer,
        responses={201: OrderSerializer, 200: OrderSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = PurchaseInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = purchases.purchase(
            PurchaseInput(
                actor_id(request),
                values["request_key"],
                PurchaseDefinition(
                    values["customer_id"],
                    values["product_id"],
                    int(values["expected_revision"]),
                    values["service_name"],
                ),
            )
        )
        return Response(OrderSerializer(result.order).data, status=201 if result.created else 200)


class OrderView(APIView):
    @extend_schema(operation_id="read_order", responses=OrderSerializer)
    def get(self, request: Request, order_id: UUID) -> Response:
        result = orders.read(order_id, actor_id(request))
        return Response(OrderSerializer(result).data)
