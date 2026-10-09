from dataclasses import dataclass

from src.modules.accounts.resellers.domain.models import ResellerModel
from src.modules.sales.reseller_billing.domain.dtos import (
    ResellerBillingSnapshot,
)
from src.modules.sales.reseller_catalog.domain.results import ResellerPlanFacts


@dataclass(frozen=True, slots=True)
class PurchaseBilling:
    reseller: ResellerModel
    payer_customer_id: int
    agreement: ResellerPlanFacts
    price_rial: int
    snapshot: ResellerBillingSnapshot


@dataclass(frozen=True, slots=True)
class RenewalBilling:
    available: bool
    price_rial: int
