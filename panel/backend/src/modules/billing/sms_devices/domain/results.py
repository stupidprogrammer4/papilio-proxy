from datetime import datetime

from pydantic import BaseModel


class SmsDeviceRead(BaseModel):
    parser_profile_id: int | None = None
    settlement_identity_mode: str = "bank_reference_required"

    approval_mode: str
    destination_id: int | None
    id: int
    label: str
    senders: list[str]
    is_active: bool
    revision: int
    expires_at: datetime


class SmsDeviceEnrollment(BaseModel):
    device: SmsDeviceRead
    api_key: str
