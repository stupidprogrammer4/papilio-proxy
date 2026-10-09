from typing import Literal

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import BaseModel, Field, SecretStr, field_validator

from src.modules.accounts.customers.domain.dtos import CustomerAccessState

RESELLER_AREAS = (
    "customers",
    "subscriptions",
    "catalog",
    "wallet",
    "team",
    "support",
)
RESELLER_LEVELS = ("read", "create", "update", "manage")
RESELLER_SCOPES = frozenset(
    {"*"}
    | {
        f"{area}:{level}"
        for area in RESELLER_AREAS
        for level in RESELLER_LEVELS
    }
)


class ResellerAccessFields(BaseModel):
    login_enabled: bool
    sales_enabled: bool
    renewals_enabled: bool


class ResellerAccess(ResellerAccessFields, BaseDTO):
    pass


class ResellerPolicy(BaseDTO):
    require_active_owner: bool
    customer_creation_enabled: bool
    customer_access_override_enabled: bool
    new_customer_access: CustomerAccessState
    customer_capacity: int = Field(gt=0)
    account_capacity: int = Field(gt=0)
    plan_capacity: int = Field(gt=0)
    max_sessions_per_account: int = Field(gt=0)
    session_limit_mode: Literal["reject_new", "replace_oldest"]
    payer_mode: Literal["reseller_wallet", "customer_wallet", "either"]
    customer_self_purchase: bool
    renewal_price_mode: Literal["purchase_snapshot", "current_agreement"]
    renewal_availability_mode: Literal[
        "purchase_snapshot", "current_agreement"
    ]
    customer_can_disable_reseller_renewal: bool


class ResellerScopes(BaseDTO):
    scopes: list[str]

    @field_validator("scopes")
    @classmethod
    def supported_scopes(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or not set(value) <= RESELLER_SCOPES:
            raise ValueError("Distinct supported reseller scopes are required")
        return value


class ResellerDefaults(BaseDTO):
    access: ResellerAccess
    policy: ResellerPolicy
    owner_access: ResellerScopes
    owner_is_active: bool
    wallet_customer_access: CustomerAccessState


class ResellerCredentials(BaseDTO):
    username: str = Field(
        min_length=3, max_length=64, pattern=r"^[a-z0-9_.-]+$"
    )
    password: SecretStr = Field(min_length=8, max_length=256)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class ResellerCreate(BaseDTO):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9_-]+$")
    title: str = Field(min_length=2, max_length=120)
    owner: ResellerCredentials
    access: ResellerAccess | None = None
    policy: ResellerPolicy | None = None
    owner_access: ResellerScopes | None = None
    owner_is_active: bool | None = None


class ResellerWrite(BaseDTO):
    expected_revision: int = Field(ge=1)
    title: str = Field(min_length=2, max_length=120)
    access: ResellerAccess
    policy: ResellerPolicy
    reason: str = Field(min_length=3, max_length=250)


class ResellerSearch(BaseQuery):
    q: str | None = Field(default=None, max_length=120)
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class ResellerAccountCreate(ResellerCredentials, ResellerScopes):
    is_active: bool


class ResellerAccountWrite(ResellerScopes):
    expected_revision: int = Field(ge=1)
    is_active: bool
    reason: str = Field(min_length=3, max_length=250)


class ResellerPasswordWrite(BaseDTO):
    expected_revision: int = Field(ge=1)
    password: SecretStr = Field(min_length=8, max_length=256)
    reason: str = Field(min_length=3, max_length=250)
