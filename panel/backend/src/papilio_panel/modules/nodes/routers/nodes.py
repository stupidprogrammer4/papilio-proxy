"""Owner-scoped node records, durable work and private bootstrap downloads."""

from io import BytesIO
from uuid import UUID

from django.http import FileResponse
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..domain import (
    AgentRuntime,
    CertificatePolicy,
    NodeCreate,
    NodeDefinition,
    NodeSearch,
    NodeWorkKind,
    WorkSubmission,
)
from ..providers import nodes
from .schemas import (
    CreationSerializer,
    NodeDefaultsSerializer,
    NodeInputSerializer,
    NodePageSerializer,
    NodeSearchSerializer,
    NodeSerializer,
    WorkInputSerializer,
    WorkSerializer,
)


def actor_id(request: Request) -> int:
    identifier = request.user.pk
    if identifier is None:
        raise NotAuthenticated()
    return identifier


class NodesView(APIView):
    serializer_class = NodeInputSerializer

    @extend_schema(
        operation_id="list_nodes", parameters=[NodeSearchSerializer], responses=NodePageSerializer
    )
    def get(self, request: Request) -> Response:
        query = NodeSearchSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        result = nodes.search(
            NodeSearch(
                actor_id=actor_id(request),
                query=values["q"],
                page=values["page"],
                page_size=values["page_size"],
            )
        )
        return Response(NodePageSerializer(result).data)

    @extend_schema(responses={202: CreationSerializer})
    def post(self, request: Request) -> Response:
        serializer = NodeInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = nodes.create(
            NodeCreate(
                actor_id=actor_id(request),
                request_key=values["request_key"],
                definition=NodeDefinition(
                    name=values["name"],
                    endpoint_url=values["endpoint_url"],
                    runtime=AgentRuntime(**values["runtime"]),
                    certificate_policy=CertificatePolicy(**values["certificate_policy"]),
                ),
            )
        )
        return Response(CreationSerializer(result).data, status=202)


class NodeView(APIView):
    serializer_class = NodeSerializer

    def get(self, request: Request, node_id: UUID) -> Response:
        node = nodes.read(node_id, actor_id(request))
        return Response(NodeSerializer(node).data)


class NodeOperationsView(APIView):
    serializer_class = WorkInputSerializer

    @extend_schema(responses={202: WorkSerializer})
    def post(self, request: Request, node_id: UUID) -> Response:
        serializer = WorkInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        operation = nodes.submit(
            WorkSubmission(
                actor_id=actor_id(request),
                node_id=node_id,
                request_key=values["request_key"],
                kind=NodeWorkKind(values["kind"]),
            )
        )
        return Response(WorkSerializer(operation).data, status=202)


class NodeOperationView(APIView):
    serializer_class = WorkSerializer

    def get(self, request: Request, node_id: UUID, operation_id: UUID) -> Response:
        operation = nodes.read_work(node_id, operation_id, actor_id(request))
        return Response(WorkSerializer(operation).data)


class NodeBootstrapView(APIView):
    @extend_schema(request=None, responses={(200, "application/zip"): bytes})
    def post(self, request: Request, node_id: UUID) -> FileResponse:
        content = nodes.bootstrap(node_id, actor_id(request))
        response = FileResponse(
            BytesIO(content),
            as_attachment=True,
            filename=f"papilio-node-{node_id}.zip",
            content_type="application/zip",
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class NodeDefaultsView(APIView):
    serializer_class = NodeDefaultsSerializer

    def get(self, request: Request) -> Response:
        defaults = nodes.defaults(actor_id(request))
        return Response(NodeDefaultsSerializer(defaults).data)
