"""Resolve the native authenticated principal for payment adapters."""

from rest_framework.exceptions import NotAuthenticated
from rest_framework.request import Request


def actor_id(request: Request) -> int:
    identifier = request.user.pk
    if identifier is None:
        raise NotAuthenticated()
    return identifier
