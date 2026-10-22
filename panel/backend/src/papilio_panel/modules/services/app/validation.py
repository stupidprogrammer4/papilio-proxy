"""Pure validation of persistent service creation inputs."""

from dataclasses import replace
from uuid import UUID

from papilio_panel.shared.errors import InvalidInput

from ..domain import ServiceDefinition


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
