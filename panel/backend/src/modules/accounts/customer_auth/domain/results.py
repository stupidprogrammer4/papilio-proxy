from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel

from src.modules.accounts.customer_auth.domain.models import (
    CustomerSessionModel,
)
from src.modules.accounts.customers.domain.models import CustomerModel


@dataclass(frozen=True, slots=True)
class CustomerPrincipal:
    customer_id: int
    display_name: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CustomerSessionFacts:
    customer: CustomerModel
    session: CustomerSessionModel


@dataclass(frozen=True, slots=True)
class IssuedCustomerSession:
    token: str
    principal: CustomerPrincipal


class CustomerLoginLink(BaseModel):
    url: str
    expires_at: datetime
