"""Native cookie authentication and CSRF adapters."""

from dataclasses import asdict

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.http import HttpRequest
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from ..domain import AdminPrincipal, AdminSession
from ..providers import admin_access


def session_data(request: HttpRequest, principal: AdminPrincipal) -> AdminSession:
    admin_access.authorize(principal)
    return AdminSession(
        username=principal.username,
        scopes=(
            "system:read",
            "system:write",
            "nodes:read",
            "nodes:write",
            "bots:read",
            "bots:write",
            "cores:read",
            "cores:write",
            "services:read",
            "services:write",
            "sales:read",
            "sales:write",
        )
        if principal.is_superuser
        else ("system:read", "bots:read", "bots:write"),
        csrf_token=get_token(request),
    )


class CredentialsSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=1024)


class CsrfSerializer(serializers.Serializer):
    csrf_token = serializers.CharField()


class SessionSerializer(CsrfSerializer):
    username = serializers.CharField()
    scopes = serializers.ListField(child=serializers.CharField())


class CsrfView(APIView):
    serializer_class = CsrfSerializer
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        return Response({"csrf_token": get_token(request._request)})


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    serializer_class = CredentialsSerializer

    @extend_schema(responses=SessionSerializer)
    def post(self, request: Request) -> Response:
        values = CredentialsSerializer(data=request.data)
        values.is_valid(raise_exception=True)
        user = authenticate(
            request._request,
            username=values.validated_data["username"],
            password=values.validated_data["password"],
        )
        if not isinstance(user, User) or user.pk is None:
            raise AuthenticationFailed("The supplied credentials cannot access this panel.")
        principal = AdminPrincipal(
            id=user.pk,
            username=user.get_username(),
            is_active=user.is_active,
            is_staff=user.is_staff,
            is_superuser=user.is_superuser,
        )
        admin_access.authorize(principal)
        login(request._request, user)
        return Response(asdict(session_data(request._request, principal)))


class SessionView(APIView):
    serializer_class = SessionSerializer
    permission_classes = [IsAdminUser]

    def get(self, request: Request) -> Response:
        user = request.user
        if not isinstance(user, User) or user.pk is None:
            raise NotAuthenticated()
        principal = AdminPrincipal(
            id=user.pk,
            username=user.get_username(),
            is_active=user.is_active,
            is_staff=user.is_staff,
            is_superuser=user.is_superuser,
        )
        return Response(asdict(session_data(request._request, principal)))


class LogoutView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        logout(request._request)
        return Response(status=204)
