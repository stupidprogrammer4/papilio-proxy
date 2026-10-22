"""Pure validation of the supported native Xray account contract."""

from uuid import UUID

from papilio_panel.shared.errors import InvalidInput

from ..domain import VlessUser, XrayUserIdentity


def validate_identity(values: XrayUserIdentity) -> None:
    if not values.inbound_tag or values.inbound_tag.strip() != values.inbound_tag:
        raise InvalidInput("Choose a nonempty native inbound tag without surrounding spaces.")
    if (
        not values.email
        or values.email.strip() != values.email
        or values.email.lower() != values.email
        or ">>>" in values.email
    ):
        raise InvalidInput("Choose a lowercase native user identity without stats delimiters.")


def validate_vless(values: VlessUser) -> None:
    validate_identity(values.identity)
    if not isinstance(values.identifier, UUID) or values.flow not in {"", "xtls-rprx-vision"}:
        raise InvalidInput("Use a UUID and a supported native VLESS flow.")
    if type(values.level) is not int or not 0 <= values.level <= 4294967295:
        raise InvalidInput("The native user level must fit an unsigned 32-bit integer.")
