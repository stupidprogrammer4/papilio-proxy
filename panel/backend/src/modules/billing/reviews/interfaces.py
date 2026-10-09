from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.billing.reviews.domain.dtos import PaymentReviewSearch
from src.modules.billing.reviews.domain.models import PaymentReviewModel
from src.modules.billing.reviews.domain.results import PaymentReviewFacts


class IPaymentReviewCommand(Protocol):
    def check(self, topup_id: int) -> Awaitable[PaymentReviewModel]: ...


class IPaymentReviewQuery(Protocol):
    def due_ids(self) -> Awaitable[list[int]]: ...
    def search(
        self, data: PaymentReviewSearch
    ) -> Awaitable[ServicePage[PaymentReviewFacts]]: ...
