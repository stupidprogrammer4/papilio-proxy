from typing import Literal

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field

CoreKind = Literal["xray", "sing_box", "wireguard", "openvpn", "hysteria"]


class CoreCreate(BaseDTO):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    label: str = Field(min_length=2, max_length=100)
    kind: CoreKind


class CoreSearch(BaseQuery):
    q: str | None = Field(default=None, max_length=100)
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)
