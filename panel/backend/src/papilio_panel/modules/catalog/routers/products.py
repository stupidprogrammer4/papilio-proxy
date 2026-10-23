"""Catalogue product configuration and immutable offer resource adapters."""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from papilio_panel.shared.money import Currency

from ..domain import ProductChange, ProductCreate, ProductDefinition, ProductSearch
from ..providers import products
from .schemas import (
    ProductChangeSerializer,
    ProductInputSerializer,
    ProductOfferSerializer,
    ProductPageSerializer,
    ProductSerializer,
    SearchSerializer,
)


def actor_id(request: Request) -> int:
    identifier = request.user.pk
    if identifier is None:
        raise NotAuthenticated()
    return identifier


class ProductsView(APIView):
    @extend_schema(
        operation_id="list_products", parameters=[SearchSerializer], responses=ProductPageSerializer
    )
    def get(self, request: Request) -> Response:
        serializer = SearchSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = products.search(
            ProductSearch(
                actor_id(request),
                values["q"],
                values["page"],
                values["page_size"],
                values["active_only"],
            )
        )
        return Response(ProductPageSerializer(result).data)

    @extend_schema(
        operation_id="create_product",
        request=ProductInputSerializer,
        responses={201: ProductSerializer, 200: ProductSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = ProductInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        definition = values["definition"]
        result = products.create(
            ProductCreate(
                actor_id(request),
                values["request_key"],
                ProductDefinition(
                    definition["name"],
                    definition["core_id"],
                    definition["inbound_id"],
                    definition["price_minor"],
                    Currency(definition["currency"]),
                    definition["user_level"],
                    definition["is_active"],
                ),
            )
        )
        return Response(
            ProductSerializer(result.product).data, status=201 if result.created else 200
        )


class ProductView(APIView):
    @extend_schema(operation_id="read_product", responses=ProductSerializer)
    def get(self, request: Request, product_id: UUID) -> Response:
        result = products.read(product_id, actor_id(request))
        return Response(ProductSerializer(result).data)

    @extend_schema(
        operation_id="change_product", request=ProductChangeSerializer, responses=ProductSerializer
    )
    def put(self, request: Request, product_id: UUID) -> Response:
        serializer = ProductChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        definition = values["definition"]
        result = products.change(
            ProductChange(
                actor_id(request),
                product_id,
                int(values["expected_revision"]),
                ProductDefinition(
                    definition["name"],
                    definition["core_id"],
                    definition["inbound_id"],
                    definition["price_minor"],
                    Currency(definition["currency"]),
                    definition["user_level"],
                    definition["is_active"],
                ),
            )
        )
        return Response(ProductSerializer(result).data)


class ProductOfferView(APIView):
    @extend_schema(operation_id="read_product_offer", responses=ProductOfferSerializer)
    def get(self, request: Request, offer_id: UUID) -> Response:
        result = products.read_offer(offer_id, actor_id(request))
        return Response(ProductOfferSerializer(result).data)
