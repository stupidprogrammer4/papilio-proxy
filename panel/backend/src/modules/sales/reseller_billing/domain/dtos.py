from dataclasses import dataclass
from typing import Literal

from papilio.schemas.inputs import BaseDTO
from pydantic import Field

from src.modules.accounts.resellers.domain.results import ResellerPrincipal
from src.modules.sales.reseller_catalog.domain.dtos import AgreementPrice
from src.modules.sales.subscriptions.domain.dtos import SubscriptionCreate

PayerMode = Literal["reseller_wallet", "customer_wallet"]


@dataclass(frozen=True, slots=True)
class PurchaseActor:
    staff_id: int | None = None
    reseller: ResellerPrincipal | None = None
    payer_mode: PayerMode | None = None

    def __post_init__(self) -> None:
        if self.staff_id is not None and self.reseller is not None:
            raise ValueError("Purchase actors belong to one realm")


class ResellerBillingSnapshot(BaseDTO):
    agreement_revision: int = Field(ge=1)
    price: AgreementPrice
    payer_mode: PayerMode
    renewal_price_mode: Literal["purchase_snapshot", "current_agreement"]
    renewal_availability_mode: Literal[
        "purchase_snapshot", "current_agreement"
    ]


class AdminSubscriptionPurchase(SubscriptionCreate):
    payer_mode: PayerMode | None = None


class ResellerSubscriptionPurchase(SubscriptionCreate):
    payer_mode: PayerMode
