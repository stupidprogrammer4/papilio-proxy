from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field, field_validator

from src.modules.network.nodes.domain.dtos import NodeCreate


class RoutingSearch(BaseQuery):
    q: str | None = Field(default=None, max_length=100)
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class HostSearch(RoutingSearch):
    configuration_id: int | None = Field(default=None, gt=0)


class HostWrite(BaseDTO):
    label: str = Field(min_length=2, max_length=100)
    address: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    is_enabled: bool

    @field_validator("address")
    @classmethod
    def valid_address(cls, value: str) -> str:
        return NodeCreate.valid_host(value)


class GroupWrite(BaseDTO):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=2, max_length=100)
    is_enabled: bool


class MembershipWrite(BaseDTO):
    label: str | None = Field(default=None, min_length=2, max_length=100)
    address: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    server_name: str | None = Field(
        default=None, min_length=1, max_length=253, pattern=r"^[A-Za-z0-9.-]+$"
    )
    is_enabled: bool
    sort_order: int

    @field_validator("address")
    @classmethod
    def valid_address(cls, value: str | None) -> str | None:
        return None if value is None else NodeCreate.valid_host(value)
