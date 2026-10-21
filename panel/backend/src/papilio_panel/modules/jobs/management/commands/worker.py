"""Run a native prefork worker using the producer's queue configuration."""

from argparse import ArgumentParser
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from papilio_panel.config.celery import app
from papilio_panel.config.queues import QueueKind, queue_name


class Command(BaseCommand):
    help = "Run one native I/O or CPU Celery worker."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--kind", choices=[kind.value for kind in QueueKind], required=True)
        parser.add_argument("--concurrency", type=int)
        parser.add_argument("--loglevel", default="INFO")

    def handle(self, *args: Any, **options: Any) -> None:
        kind = QueueKind(options["kind"])
        concurrency = options["concurrency"] or (
            settings.PAPILIO_IO_CONCURRENCY
            if kind == QueueKind.IO
            else settings.PAPILIO_CPU_CONCURRENCY
        )
        app.worker_main(
            [
                "worker",
                "--pool=prefork",
                f"--queues={queue_name(kind)}",
                f"--concurrency={concurrency}",
                f"--loglevel={options['loglevel']}",
                f"--hostname={settings.PAPILIO_NAMESPACE}-{kind.value}@%h",
            ]
        )
