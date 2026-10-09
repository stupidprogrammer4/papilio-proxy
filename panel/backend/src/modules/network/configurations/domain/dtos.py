from ipaddress import ip_address, ip_interface, ip_network
from typing import Annotated, Literal

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import BaseModel, Field, field_validator, model_validator

from src.modules.network.configurations.domain.openvpn import OpenVpnOptions


class ListenOptions(BaseModel):
    listen_address: str

    @field_validator("listen_address")
    @classmethod
    def valid_listen(cls, value: str) -> str:
        return str(ip_address(value))


class RealityOptions(ListenOptions):
    protocol: Literal["vless_reality"]
    server_name: str = Field(pattern=r"^[A-Za-z0-9.-]+$", max_length=253)
    target_port: int = Field(ge=1, le=65535)


class TlsOptions(ListenOptions):
    protocol: Literal["vless_tls", "vmess_tls", "trojan_tls"]
    server_name: str = Field(pattern=r"^[A-Za-z0-9.-]+$", max_length=253)
    certificate_path: str = Field(
        min_length=1, max_length=1024, pattern=r"^[^\r\n]+$"
    )
    private_key_path: str = Field(
        min_length=1, max_length=1024, pattern=r"^[^\r\n]+$"
    )
    transport: Literal["tcp", "ws", "grpc"]
    transport_path: str | None = Field(
        default=None, max_length=255, pattern=r"^[^\r\n]+$"
    )

    @model_validator(mode="after")
    def transport_options(self) -> "TlsOptions":
        if self.transport == "ws" and (
            not self.transport_path or not self.transport_path.startswith("/")
        ):
            raise ValueError("WebSocket requires an absolute path")
        if self.transport == "grpc" and not self.transport_path:
            raise ValueError("gRPC requires a service name")
        return self


class ShadowsocksOptions(ListenOptions):
    protocol: Literal["shadowsocks"]


class HysteriaOptions(ListenOptions):
    protocol: Literal["hysteria2"]
    server_name: str = Field(pattern=r"^[A-Za-z0-9.-]+$", max_length=253)
    certificate_path: str = Field(
        min_length=1, max_length=1024, pattern=r"^[^\r\n]+$"
    )
    private_key_path: str = Field(
        min_length=1, max_length=1024, pattern=r"^[^\r\n]+$"
    )


class WireguardOptions(BaseModel):
    protocol: Literal["wireguard"]
    server_address: str
    client_subnet: str
    allowed_ips: list[str] = Field(min_length=1)
    dns: list[str] = Field(min_length=1)

    @field_validator("server_address")
    @classmethod
    def valid_address(cls, value: str) -> str:
        return str(ip_interface(value))

    @field_validator("client_subnet")
    @classmethod
    def valid_subnet(cls, value: str) -> str:
        return str(ip_network(value))

    @field_validator("allowed_ips")
    @classmethod
    def valid_routes(cls, value: list[str]) -> list[str]:
        return [str(ip_network(item)) for item in value]

    @field_validator("dns")
    @classmethod
    def valid_dns(cls, value: list[str]) -> list[str]:
        return [str(ip_address(item)) for item in value]

    @model_validator(mode="after")
    def same_subnet(self) -> "WireguardOptions":
        if ip_interface(self.server_address).ip not in ip_network(
            self.client_subnet
        ):
            raise ValueError("Server address must belong to client subnet")
        return self


ConfigurationOptions = Annotated[
    RealityOptions
    | TlsOptions
    | ShadowsocksOptions
    | HysteriaOptions
    | WireguardOptions
    | OpenVpnOptions,
    Field(discriminator="protocol"),
]


class ConfigurationCreate(BaseDTO):
    node_id: int = Field(gt=0)
    core_id: int | None = Field(default=None, gt=0)
    listen_port: int | None = Field(default=None, ge=1, le=65535)
    label: str = Field(min_length=2, max_length=100)
    options: ConfigurationOptions


class ConfigurationUpdate(BaseDTO):
    expected_revision: int | None = Field(default=None, gt=0)
    label: str = Field(min_length=2, max_length=100)
    options: ConfigurationOptions


class ProfileCreate(BaseDTO):
    subscription_id: int = Field(gt=0)
    client_address: str | None = None

    @field_validator("client_address")
    @classmethod
    def valid_address(cls, value: str | None) -> str | None:
        return None if value is None else str(ip_interface(value))


class ConfigurationSearch(BaseQuery):
    core_id: int | None = Field(default=None, gt=0)
    node_id: int | None = Field(default=None, gt=0)
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class ProfileSearch(BaseQuery):
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class PublicProfileSearch(BaseQuery):
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class ConfigurationServerExportRequest(BaseDTO):
    configuration_ids: list[Annotated[int, Field(gt=0)]] = Field(min_length=1)
