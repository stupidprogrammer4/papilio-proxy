"""Translate application errors at the HTTP boundary."""

from typing import Any

from rest_framework.response import Response
from rest_framework.views import exception_handler

from .errors import ApplicationError, AuthenticationRejected, Conflict, InvalidInput, Missing


def handle_exception(error: Exception, context: dict[str, Any]) -> Response | None:
    """Keep internal errors and credentials out of public responses."""
    response = exception_handler(error, context)
    if isinstance(error, ApplicationError):
        status = 500
        if isinstance(error, Conflict):
            status = 409
        elif isinstance(error, InvalidInput):
            status = 400
        elif isinstance(error, AuthenticationRejected):
            status = 401
        elif isinstance(error, Missing):
            status = 404
        response = Response({"code": error.code, "detail": str(error)}, status=status)
    return response
