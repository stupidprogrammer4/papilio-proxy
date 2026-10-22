"""Common core identity and specialized Xray registration/read contracts."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class CoreKind(StrEnum):
    XRAY = "xray"
    HYSTERIA2 = "hysteria2"
    WIREGUARD = "wireguard"
    OPENVPN = "openvpn"


@dataclass(frozen=True)
class XraySettings:
    default_user_level: int = 0


@dataclass(frozen=True)
class XrayRegistration:
    actor_id: int
    request_key: UUID
    node_id: UUID
    name: str
    xray: XraySettings = XraySettings()


@dataclass(frozen=True)
class CoreRead:
    id: UUID
    owner_id: int
    node_id: UUID
    kind: CoreKind
    name: str
    xray: XraySettings


@dataclass(frozen=True)
class CoreCreation:
    core: CoreRead
    created: bool


@dataclass(frozen=True)
class XrayInboundDefinition:
    tag: str
    public_host: str
    port: int


@dataclass(frozen=True)
class XrayInboundRegistration:
    actor_id: int
    core_id: UUID
    request_key: UUID
    definition: XrayInboundDefinition


@dataclass(frozen=True)
class XrayInboundRead:
    id: UUID
    core_id: UUID
    tag: str
    public_host: str
    port: int


@dataclass(frozen=True)
class InboundCreation:
    inbound: XrayInboundRead
    created: bool


@dataclass(frozen=True)
class CoreSearch:
    actor_id: int
    query: str = ""
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True)
class InboundSearch:
    actor_id: int
    core_id: UUID
    query: str = ""
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True)
class CorePage:
    items: tuple[CoreRead, ...]
    count: int
    page: int
    page_size: int


@dataclass(frozen=True)
class InboundPage:
    items: tuple[XrayInboundRead, ...]
    count: int
    page: int
    page_size: int
