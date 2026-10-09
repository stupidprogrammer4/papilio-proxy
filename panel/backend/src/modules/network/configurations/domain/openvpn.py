from ipaddress import IPv4Address, IPv4Network, ip_address, ip_network
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class OpenVpnTun(BaseModel):
    mode: Literal["tun"]
    network: str

    @field_validator("network")
    @classmethod
    def valid_network(cls, value: str) -> str:
        network = ip_network(value)
        if not isinstance(network, IPv4Network) or network.prefixlen > 29:
            raise ValueError(
                "OpenVPN routed pool requires an IPv4 subnet "
                "with room for reserved addresses"
            )
        return str(network)


class OpenVpnBridge(BaseModel):
    mode: Literal["tap"]
    bridge_address: str
    network: str
    pool_start: str
    pool_end: str

    @model_validator(mode="after")
    def valid_pool(self) -> "OpenVpnBridge":
        network = ip_network(self.network)
        bridge = ip_address(self.bridge_address)
        first = ip_address(self.pool_start)
        last = ip_address(self.pool_end)
        if not isinstance(network, IPv4Network) or not all(
            isinstance(value, IPv4Address) for value in (bridge, first, last)
        ):
            raise ValueError("OpenVPN bridge addresses must be IPv4")
        if (
            any(
                value not in network
                or value
                in (network.network_address, network.broadcast_address)
                for value in (bridge, first, last)
            )
            or int(first) > int(last)
            or int(first) <= int(bridge) <= int(last)
        ):
            raise ValueError(
                "Bridge address and pool must be disjoint "
                "usable addresses in the same network"
            )
        self.network = str(network)
        self.bridge_address, self.pool_start, self.pool_end = (
            str(bridge),
            str(first),
            str(last),
        )
        return self


OpenVpnTopology = Annotated[
    OpenVpnTun | OpenVpnBridge, Field(discriminator="mode")
]
OpenVpnKeyType = Literal["ec_p256", "rsa_2048", "rsa_3072", "rsa_4096"]
OpenVpnCipher = Literal["AES-256-GCM", "AES-128-GCM", "CHACHA20-POLY1305"]


class OpenVpnOptions(BaseModel):
    protocol: Literal["openvpn"]
    listen_address: str
    ca_name: str = Field(
        pattern=r"^[A-Za-z0-9 ._-]+$", min_length=1, max_length=64
    )
    server_name: str = Field(
        pattern=r"^[A-Za-z0-9.-]+$", min_length=1, max_length=64
    )
    transport: Literal["udp", "tcp"]
    topology: OpenVpnTopology
    routes: list[str]
    dns: list[str]
    redirect_gateway: bool
    client_to_client: bool
    data_ciphers: list[OpenVpnCipher] = Field(min_length=1)
    tls_min_version: Literal["1.2", "1.3"]
    tls_crypt: bool
    key_type: OpenVpnKeyType
    ca_validity_days: int = Field(gt=0)
    server_validity_days: int = Field(gt=0)
    client_validity_days: int = Field(gt=0)
    crl_validity_seconds: int = Field(gt=0)
    keepalive_seconds: int = Field(gt=0)
    restart_seconds: int = Field(gt=0)
    max_clients: int = Field(gt=0)
    # Linux sun_path reserves one of its 108 ABI bytes for the terminator.
    management_socket: str = Field(
        pattern=r"^/[A-Za-z0-9_./-]+$", max_length=107
    )
    verbosity: int = Field(ge=0, le=11)

    @field_validator("listen_address")
    @classmethod
    def valid_listen(cls, value: str) -> str:
        return str(ip_address(value))

    @field_validator("routes")
    @classmethod
    def valid_routes(cls, value: list[str]) -> list[str]:
        return [str(ip_network(item)) for item in value]

    @field_validator("dns")
    @classmethod
    def valid_dns(cls, value: list[str]) -> list[str]:
        return [str(ip_address(item)) for item in value]

    @field_validator("management_socket")
    @classmethod
    def valid_socket(cls, value: str) -> str:
        if ".." in value.split("/") or value.endswith("/") or value == "/":
            raise ValueError(
                "Management socket requires an absolute file path "
                "without parent traversal"
            )
        canonical = "/" + str(PurePosixPath(value)).lstrip("/")
        if canonical == "/":
            raise ValueError("Management socket requires a file path")
        return canonical

    @model_validator(mode="after")
    def valid_certificates(self) -> "OpenVpnOptions":
        if (
            max(self.client_validity_days, self.server_validity_days)
            >= self.ca_validity_days
        ):
            raise ValueError(
                "Leaf certificates must expire before their authority"
            )
        if self.restart_seconds <= self.keepalive_seconds:
            raise ValueError(
                "Keepalive restart interval must exceed the ping interval"
            )
        if len(self.data_ciphers) != len(set(self.data_ciphers)):
            raise ValueError("Negotiated data ciphers must be distinct")
        return self


class OpenVpnServerMaterial(BaseModel):
    ca_certificate: str
    server_certificate: str
    server_private_key: str
    tls_crypt_key: str | None


class OpenVpnPkiMaterial(OpenVpnServerMaterial):
    ca_private_key: str | None


class OpenVpnCertificate(BaseModel):
    certificate: str
    serial: str


class OpenVpnClientCertificate(OpenVpnCertificate):
    private_key: str | None


class OpenVpnCapacity(BaseModel):
    enabled: bool
    max_ca_validity_days: int = Field(gt=0)
    max_server_validity_days: int = Field(gt=0)
    max_client_validity_days: int = Field(gt=0)
    max_crl_validity_seconds: int = Field(gt=0)
    max_clients: int = Field(gt=0)
    max_routes: int = Field(ge=0)
    max_dns_servers: int = Field(ge=0)
    max_keepalive_seconds: int = Field(gt=0)
    max_restart_seconds: int = Field(gt=0)
    allowed_key_types: list[OpenVpnKeyType] = Field(min_length=1)
