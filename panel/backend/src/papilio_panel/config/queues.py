"""One queue naming contract for task producers and native workers."""

from enum import StrEnum

from django.conf import settings


class QueueKind(StrEnum):
    IO = "io"
    CPU = "cpu"


def queue_name(kind: QueueKind) -> str:
    return settings.PAPILIO_QUEUE_NAMES[kind.value]
