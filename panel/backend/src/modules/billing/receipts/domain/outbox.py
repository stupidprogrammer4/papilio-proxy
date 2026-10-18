from pydantic import BaseModel, Field


class ReceiptOcrOutboxClaim(BaseModel):
    outbox_id: int = Field(gt=0)
    receipt_id: int = Field(gt=0)
    claim_token: str = Field(min_length=1)
