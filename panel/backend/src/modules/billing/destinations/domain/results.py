from pydantic import BaseModel

from src.modules.billing.destinations.domain.dtos import PaymentKind


class PaymentInstruction(BaseModel):
    destination_id: int
    title: str
    kind: PaymentKind
    account: str
    recipient: str
    bank_name: str
    instructions: str | None


class DestinationDetails(PaymentInstruction):
    is_active: bool
    receiving_alias_id: int | None = None
    revision: int = 1
