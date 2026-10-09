from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field, SecretStr, field_validator

STAFF_SCOPE_AREAS = (
    "resellers",
    "staff",
    "customers",
    "catalog",
    "payments",
    "subscriptions",
    "network",
    "settings",
    "support",
    "notifications",
)
STAFF_SCOPE_LEVELS = ("read", "create", "update", "delete", "manage", "*")
STAFF_SCOPES = frozenset(
    {"*"}
    | {
        f"{area}:{level}"
        for area in STAFF_SCOPE_AREAS
        for level in STAFF_SCOPE_LEVELS
    }
)


class StaffCredentials(BaseDTO):
    username: str = Field(min_length=3, max_length=64)
    password: SecretStr = Field(min_length=8, max_length=256)


class StaffSearch(BaseQuery):
    q: str | None = Field(default=None, max_length=64)
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class StaffScopes(BaseDTO):
    scopes: list[str]

    @field_validator("scopes")
    @classmethod
    def valid_scopes(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values) or any(
            value not in STAFF_SCOPES for value in values
        ):
            raise ValueError(
                "Staff grants must be distinct supported capabilities"
            )
        return values


class StaffCreate(StaffCredentials, StaffScopes):
    is_active: bool


class StaffAccessWrite(StaffScopes):
    is_active: bool
    expected_is_active: bool
    expected_scopes: list[str]


class StaffPasswordWrite(BaseDTO):
    password: SecretStr = Field(min_length=8, max_length=256)
