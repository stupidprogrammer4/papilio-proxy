from dataclasses import dataclass
from datetime import datetime

from src.modules.accounts.customers.domain.models import CustomerModel
from src.modules.accounts.resellers.domain.models import (
    ResellerAccountModel,
    ResellerModel,
    ResellerSessionModel,
)


@dataclass(frozen=True, slots=True)
class ResellerPrincipal:
    reseller_id: int
    account_id: int
    title: str
    username: str
    scopes: frozenset[str]
    csrf_token: str
    expires_at: datetime
    account_revision: int
    reseller_access_revision: int


@dataclass(frozen=True, slots=True)
class IssuedResellerSession:
    token: str
    principal: ResellerPrincipal


@dataclass(frozen=True, slots=True)
class ResellerSessionFacts:
    reseller: ResellerModel
    account: ResellerAccountModel
    session: ResellerSessionModel


@dataclass(frozen=True, slots=True)
class CreatedReseller:
    reseller: ResellerModel
    owner: ResellerAccountModel


@dataclass(frozen=True, slots=True)
class OwnedResellerCustomer:
    reseller: ResellerModel
    customer: CustomerModel


@dataclass(frozen=True, slots=True)
class ResellerAccountActor:
    staff_id: int | None = None
    principal: ResellerPrincipal | None = None

    def __post_init__(self) -> None:
        if (self.staff_id is None) == (self.principal is None):
            raise ValueError("Exactly one authenticated actor is required")
