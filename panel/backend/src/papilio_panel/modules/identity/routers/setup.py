"""One-time installation owner onboarding."""

from dataclasses import asdict

from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from papilio_panel.modules.local_nodes.domain import OwnerInitialization
from papilio_panel.modules.local_nodes.providers import owner_initialization
from papilio_panel.modules.local_nodes.schemas import LocalChoiceSerializer

from ..domain import OwnerSetupInput


class OwnerSetupSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=1024, write_only=True)
    username = serializers.CharField(max_length=150, validators=[UnicodeUsernameValidator()])
    password = serializers.CharField(
        max_length=1024, trim_whitespace=False, write_only=True, validators=[validate_password]
    )
    local_node = LocalChoiceSerializer(required=False)


class OwnerIdentitySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()


@method_decorator(csrf_protect, name="dispatch")
class OwnerSetupView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    serializer_class = OwnerSetupSerializer

    @extend_schema(responses={201: OwnerIdentitySerializer})
    def post(self, request: Request) -> Response:
        serializer = OwnerSetupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = OwnerSetupInput(
            token=serializer.validated_data["token"],
            username=serializer.validated_data["username"],
            password=serializer.validated_data["password"],
        )
        owner = owner_initialization.complete(
            OwnerInitialization(values, serializer.validated_data.get("local_node"))
        )
        return Response(asdict(owner), status=201)
