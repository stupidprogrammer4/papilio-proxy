"""Pure validation of persistent service creation inputs."""

from dataclasses import replace
from uuid import UUID

from papilio_panel.shared.errors import InvalidInput

from ..domain import ServiceDefinition
from ..synchronization_contracts import SynchronizationUpdate


def definition(values: ServiceDefinition) -> ServiceDefinition:
    name = values.name.strip()
    if not 1 <= len(name) <= 80:
        raise InvalidInput("Choose a service name of up to 80 characters.")
    if values.identifier is not None and not isinstance(values.identifier, UUID):
        raise InvalidInput("The native credential must be a UUID.")
    level = values.user_level
    if level is not None and (type(level) is not int or not 0 <= level <= 4294967295):
        raise InvalidInput("The native user level must fit an unsigned 32-bit integer.")
    return replace(values, name=name)


def synchronization_policy(values: SynchronizationUpdate) -> None:
    if (
        type(values.enabled) is not bool
        or type(values.interval_seconds) is not int
        or not 1 <= values.interval_seconds <= 2147483647
        or type(values.expected_revision) is not int
        or not 1 <= values.expected_revision <= 9223372036854775807
    ):
        raise InvalidInput("Choose a valid enabled flag, interval and current revision.")
