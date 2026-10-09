from typing import Literal

from papilio.api.requests.queries import BaseQuery
from pydantic import Field


class PaymentReviewSearch(BaseQuery):
    status: (
        Literal["waiting", "candidate", "ambiguous", "stale", "closed"] | None
    ) = None
    q: str | None = Field(default=None, max_length=120)
    customer_id: int | None = Field(default=None, gt=0)
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)
