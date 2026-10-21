"""Native session authentication with a browser-facing HTTP challenge."""

from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request


class AdminSessionAuthentication(SessionAuthentication):
    def authenticate_header(self, request: Request) -> str:
        return "Session"
