"""Permission-scoped bot resources; all external Telegram calls run in workers."""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..domain import BotChange, BotCreate, BotRuntime, BotSchedule, BotSearch
from ..providers import bots
from .schemas import (
    BotChangeSerializer,
    BotDefaultsSerializer,
    BotInputSerializer,
    BotPageSerializer,
    BotSearchSerializer,
    BotSerializer,
    PairingSerializer,
)


def actor_id(request: Request) -> int:
    identifier = request.user.pk
    if identifier is None:
        raise NotAuthenticated()
    return identifier


class BotDefaultsView(APIView):
    serializer_class = BotDefaultsSerializer

    def get(self, request: Request) -> Response:
        defaults = bots.defaults(actor_id(request))
        return Response(BotDefaultsSerializer(defaults).data)


class BotsView(APIView):
    serializer_class = BotInputSerializer

    @extend_schema(
        operation_id="list_bots", parameters=[BotSearchSerializer], responses=BotPageSerializer
    )
    def get(self, request: Request) -> Response:
        query = BotSearchSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        result = bots.search(
            BotSearch(
                actor_id=actor_id(request),
                query=values["q"],
                page=values["page"],
                page_size=values["page_size"],
            )
        )
        return Response(BotPageSerializer(result).data)

    @extend_schema(responses={202: BotSerializer})
    def post(self, request: Request) -> Response:
        serializer = BotInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = bots.create(
            BotCreate(
                actor_id=actor_id(request),
                request_key=values["request_key"],
                label=values["label"],
                token=values["token"],
                runtime=BotRuntime(**values["runtime"]),
                schedule=BotSchedule(**values["schedule"]),
            )
        )
        return Response(BotSerializer(result).data, status=202)


class BotView(APIView):
    serializer_class = BotSerializer

    def get(self, request: Request, bot_id: UUID) -> Response:
        result = bots.read(bot_id, actor_id(request))
        return Response(BotSerializer(result).data)

    @extend_schema(request=BotChangeSerializer, responses=BotSerializer)
    def put(self, request: Request, bot_id: UUID) -> Response:
        serializer = BotChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        result = bots.change(
            BotChange(
                actor_id=actor_id(request),
                bot_id=bot_id,
                expected_revision=int(values["expected_revision"]),
                label=values["label"],
                token=values.get("token"),
                runtime=BotRuntime(**values["runtime"]),
                schedule=BotSchedule(**values["schedule"]),
            )
        )
        return Response(BotSerializer(result).data)


class BotPairingView(APIView):
    serializer_class = PairingSerializer

    @extend_schema(request=None, responses={200: PairingSerializer})
    def post(self, request: Request, bot_id: UUID) -> Response:
        grant = bots.pair(bot_id, actor_id(request))
        return Response(
            PairingSerializer(grant).data, headers={"Cache-Control": "private, no-store"}
        )
