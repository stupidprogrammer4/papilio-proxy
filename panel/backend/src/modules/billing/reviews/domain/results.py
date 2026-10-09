from dataclasses import dataclass

from src.modules.accounts.customers.domain.models import CustomerModel
from src.modules.billing.reviews.domain.models import PaymentReviewModel
from src.modules.billing.wallet.domain.models import TopupModel


@dataclass(frozen=True, slots=True)
class PaymentMatchFacts:
    candidate_count: int
    competing_topup_count: int


@dataclass(frozen=True, slots=True)
class PaymentReviewFacts:
    review: PaymentReviewModel
    topup: TopupModel
    customer: CustomerModel
