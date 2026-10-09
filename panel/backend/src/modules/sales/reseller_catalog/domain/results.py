from dataclasses import dataclass

from src.modules.sales.catalog.domain.models import PlanModel
from src.modules.sales.reseller_catalog.domain.models import ResellerPlanModel


@dataclass(frozen=True)
class ResellerPlanFacts:
    agreement: ResellerPlanModel
    plan: PlanModel


@dataclass(frozen=True)
class ResellerPlanQuote:
    facts: ResellerPlanFacts
    price_rial: int
