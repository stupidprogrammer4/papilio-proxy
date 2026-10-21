"""Generate a short-lived owner setup token from the server terminal."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from papilio_panel.modules.identity.providers import owner_setup
from papilio_panel.shared.errors import Conflict


class Command(BaseCommand):
    help = "Print one single-use owner setup token; no token is logged or stored in plaintext."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--if-needed", action="store_true")

    def handle(self, *args: Any, **options: Any) -> str | None:
        try:
            token = owner_setup.issue_token()
        except Conflict as error:
            if options["if_needed"]:
                self.stdout.write("The installation owner is already configured.")
                return None
            raise CommandError(str(error)) from error
        return token
