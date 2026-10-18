from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field


class TopupCreate(BaseDTO):
    request_key: str | None = Field(default=None, min_length=8, max_length=128)
    destination_id: int | None = Field(default=None, gt=0)
    customer_id: int = Field(gt=0)
    amount_rial: int = Field(gt=0)


class TopupApproval(BaseDTO):
    expected_revision: int = Field(gt=0)
    bank_reference: str = Field(min_length=4, max_length=128)


class TopupRejection(BaseDTO):
    expected_revision: int = Field(gt=0)


class TopupSearch(BaseQuery):
    status: str | None = Field(
        default=None, pattern="^(pending|approved|rejected)$"
    )
    customer_id: int | None = Field(default=None, gt=0)
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class WalletLedgerSearch(BaseQuery):
    reason: str | None = Field(default=None, max_length=32)
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)
