"""Core-owned resource and existing inbound registration adapters."""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..domain import (
    CoreSearch,
    InboundSearch,
    XrayInboundDefinition,
    XrayInboundRegistration,
    XrayRegistration,
    XraySettings,
)
from ..providers import cores
from .schemas import (
    CoreInputSerializer,
    CorePageSerializer,
    CoreSerializer,
    InboundInputSerializer,
    InboundPageSerializer,
    InboundSerializer,
    SearchSerializer,
)


def actor_id(request: Request) -> int:
    identifier = request.user.pk
    if identifier is None:
        raise NotAuthenticated()
    return identifier


class XrayCoresView(APIView):
    serializer_class = CoreInputSerializer

    @extend_schema(
        operation_id="register_xray_core", responses={201: CoreSerializer, 200: CoreSerializer}
    )
    def post(self, request: Request) -> Response:
        serializer = CoreInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        creation = cores.register_xray(
            XrayRegistration(
                actor_id=actor_id(request),
                request_key=values["request_key"],
                node_id=values["node_id"],
                name=values["name"],
                xray=XraySettings(values["default_user_level"]),
            )
        )
        return Response(CoreSerializer(creation.core).data, status=201 if creation.created else 200)


class CoresView(APIView):
    serializer_class = CorePageSerializer

    @extend_schema(operation_id="list_cores", parameters=[SearchSerializer])
    def get(self, request: Request) -> Response:
        query = SearchSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        page = cores.search(
            CoreSearch(actor_id(request), values["q"], values["page"], values["page_size"])
        )
        return Response(CorePageSerializer(page).data)


class CoreView(APIView):
    serializer_class = CoreSerializer

    @extend_schema(operation_id="read_core")
    def get(self, request: Request, core_id: UUID) -> Response:
        core = cores.read(core_id, actor_id(request))
        return Response(CoreSerializer(core).data)


class XrayInboundsView(APIView):
    serializer_class = InboundInputSerializer

    @extend_schema(
        operation_id="list_xray_inbounds",
        parameters=[SearchSerializer],
        responses=InboundPageSerializer,
    )
    def get(self, request: Request, core_id: UUID) -> Response:
        query = SearchSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        page = cores.search_inbounds(
            InboundSearch(
                actor_id(request), core_id, values["q"], values["page"], values["page_size"]
            )
        )
        return Response(InboundPageSerializer(page).data)

    @extend_schema(
        operation_id="register_xray_inbound",
        responses={201: InboundSerializer, 200: InboundSerializer},
    )
    def post(self, request: Request, core_id: UUID) -> Response:
        serializer = InboundInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        creation = cores.register_inbound(
            XrayInboundRegistration(
                actor_id=actor_id(request),
                core_id=core_id,
                request_key=values["request_key"],
                definition=XrayInboundDefinition(
                    values["tag"], values["public_host"], values["port"]
                ),
            )
        )
        return Response(
            InboundSerializer(creation.inbound).data, status=201 if creation.created else 200
        )


class XrayInboundView(APIView):
    serializer_class = InboundSerializer

    @extend_schema(operation_id="read_xray_inbound")
    def get(self, request: Request, core_id: UUID, inbound_id: UUID) -> Response:
        inbound = cores.read_inbound(core_id, inbound_id, actor_id(request))
        return Response(InboundSerializer(inbound).data)
