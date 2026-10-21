"""Bounded readiness check through actual database/cache/worker observations."""

import json
import time
from dataclasses import asdict
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from ...providers import execution_health


class Command(BaseCommand):
    help = "Wait for fresh observations from both native Celery queues."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--timeout", type=int, default=120)

    def handle(self, *args: Any, **options: Any) -> None:
        deadline = time.monotonic() + max(0, options["timeout"])
        facts = execution_health.readiness()
        while (
            not (facts.database and facts.cache and facts.workers) and time.monotonic() < deadline
        ):
            time.sleep(1)
            facts = execution_health.readiness()
        self.stdout.write(json.dumps(asdict(facts)))
        if not (facts.database and facts.cache and facts.workers):
            raise CommandError("Runtime readiness did not succeed within the requested timeout.")
