from pydantic import BaseModel, Field


class ReceiptOcrRequest(BaseModel):
    receipt_id: int = Field(gt=0)
