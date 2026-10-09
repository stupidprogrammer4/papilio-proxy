import re
from datetime import datetime
from ipaddress import ip_address
from typing import Literal

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field, field_validator, model_validator

ProtocolName = Literal[
    "vless_reality",
    "vless_tls",
    "vmess_tls",
    "trojan_tls",
    "shadowsocks",
    "hysteria2",
    "wireguard",
    "openvpn",
]


class NodeCreate(BaseDTO):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    label: str = Field(min_length=2, max_length=100)
    public_host: str = Field(min_length=3, max_length=255)
    public_port: int = Field(ge=1, le=65535)
    protocol: ProtocolName

    @field_validator("public_host")
    @classmethod
    def valid_host(cls, value: str) -> str:
        try:
            return str(ip_address(value))
        except ValueError:
            host = value.encode("idna").decode("ascii")
            label = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
            if (
                len(host) > 253
                or re.fullmatch(rf"{label}(?:\.{label})*", host) is None
            ):
                raise ValueError("Host must be a domain name or IP address")
            return host.lower()


class NodeEnabled(BaseDTO):
    enabled: bool


class ProbeReceived(BaseDTO):
    event_id: str = Field(min_length=8, max_length=128)
    client_network: str = Field(min_length=2, max_length=64)
    success: bool
    latency_ms: int | None = Field(default=None, ge=0)
    sampled_at: datetime

    @field_validator("sampled_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Probe timestamp must include timezone")
        return value

    @model_validator(mode="after")
    def validate_latency(self) -> "ProbeReceived":
        if self.success and self.latency_ms is None:
            raise ValueError("Successful probes need latency_ms")
        if not self.success and self.latency_ms is not None:
            raise ValueError("Failed probes cannot report latency_ms")
        return self


class NodeSearch(BaseQuery):
    q: str | None = Field(default=None, max_length=100)
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class QualitySearch(BaseQuery):
    client_network: str = Field(min_length=2, max_length=64)
