"""Pure validation of native registration metadata and public endpoint addresses."""

from dataclasses import replace
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from papilio_panel.shared.errors import InvalidInput

from ..domain import XrayInboundDefinition, XrayRegistration


def validate_window(page: int, page_size: int, maximum: int) -> None:
    if page < 1 or not 1 <= page_size <= maximum:
        raise InvalidInput("Choose a positive page and a page size within the configured limit.")


def registration(values: XrayRegistration) -> XrayRegistration:
    name = values.name.strip()
    level = values.xray.default_user_level
    if not 1 <= len(name) <= 80:
        raise InvalidInput("Choose a core name of up to 80 characters.")
    if type(level) is not int or not 0 <= level <= 4294967295:
        raise InvalidInput("The default native user level must fit an unsigned 32-bit integer.")
    return replace(values, name=name)


def inbound_definition(values: XrayInboundDefinition) -> XrayInboundDefinition:
    if not values.tag or values.tag.strip() != values.tag or len(values.tag) > 255:
        raise InvalidInput(
            "Use a nonempty inbound tag of up to 255 characters without surrounding spaces."
        )
    if type(values.port) is not int or not 1 <= values.port <= 65535:
        raise InvalidInput("Choose a native TCP port from 1 to 65535.")
    host = values.public_host.lower()
    authority = f"[{host}]" if ":" in host else host
    address = f"http://{authority}:{values.port}"
    try:
        URLValidator(schemes=["http"])(address)
        parsed = urlsplit(address)
        if (
            parsed.hostname != host
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise InvalidInput(
                "Use only a public hostname or IP, without a URL path or credentials."
            )
    except (ValueError, ValidationError) as error:
        raise InvalidInput("Choose a valid public hostname or IP address.") from error
    return replace(values, public_host=host)
