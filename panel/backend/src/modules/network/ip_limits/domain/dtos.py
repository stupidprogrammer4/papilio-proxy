from dataclasses import dataclass
from datetime import datetime
from ipaddress import IPv6Address, ip_address
from typing import Literal

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field, field_validator


class IpLimitChoice(BaseDTO):
    enabled: bool
    max_ips: int = Field(gt=0)
    lease_seconds: int = Field(gt=0)
    ban_seconds: int = Field(gt=0)
    mode: Literal["reject_new", "replace_oldest"]


class IpPolicyConfigureChoice(IpLimitChoice):
    transition_mode: (
        Literal["drain_leases", "require_closed_receipts"] | None
    ) = None


class IpAdmission(BaseDTO):
    subscription_id: int = Field(gt=0)
    source_ip: str

    @field_validator("source_ip")
    @classmethod
    def normalized_ip(cls, value: str) -> str:
        if "%" in value:
            raise ValueError("Scoped source addresses are not supported")
        address = ip_address(value)
        if isinstance(address, IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return str(address)


class IpSessionSearch(BaseQuery):
    q: str | None = Field(default=None, max_length=45)
    state: Literal["active", "blocked", "inactive"] | None = None
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class IpManualBan(BaseDTO):
    seconds: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=250)


@dataclass(frozen=True, slots=True)
class IpSessionCriteria:
    source_ip_query: str | None
    expires_after: datetime | None = None
    expires_at_or_before: datetime | None = None
    blocked_after: datetime | None = None
    unblocked_at_or_before: datetime | None = None
