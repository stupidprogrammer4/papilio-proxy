"""Pure validation of local delivery choices and explicit parent identities."""

import ipaddress

from papilio_panel.modules.cores.domain import CoreRead, XrayInboundRead
from papilio_panel.modules.nodes.domain import NodeRead
from papilio_panel.shared.errors import Conflict, InvalidInput, Missing

from ..domain import DeliveryPolicy, LocalCreate, LocalDefinition, LocalRead


def definition(values: LocalDefinition) -> None:
    if values.inbound_tag == "management":
        raise InvalidInput("The management tag is reserved for the local core API.")
    try:
        ipaddress.ip_address(values.bind_address)
    except ValueError as error:
        raise InvalidInput("Choose a literal local inbound listen address.") from error
    if type(values.bind_port) is not int or not 1 <= values.bind_port <= 65535:
        raise InvalidInput("Choose a valid local inbound listen port.")


def delivery_policy(values: DeliveryPolicy) -> None:
    if type(values.enabled) is not bool or any(
        type(value) is not int or not 1 <= value <= 2147483647
        for value in (values.retry_interval_seconds, values.max_attempts)
    ):
        raise InvalidInput("Choose a valid delivery flag, retry interval and attempt bound.")


def same_request(current: LocalRead, values: LocalCreate) -> None:
    if (
        current.request_key != values.request_key
        or current.definition != values.definition
        or current.initial_delivery != values.delivery
    ):
        raise Conflict("The bundled runtime is already registered with other initial choices.")


def binding(current: LocalRead, node: NodeRead, core: CoreRead, inbound: XrayInboundRead) -> None:
    if (
        core.node_id != node.id
        or inbound.core_id != core.id
        or node.owner_id != current.owner_id
        or core.owner_id != current.owner_id
    ):
        raise Missing("The local node was not found.")
