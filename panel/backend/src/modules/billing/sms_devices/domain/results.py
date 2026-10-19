from datetime import datetime
from typing import Literal

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
    connection_state: Literal[
        "unknown", "recent", "stale", "disabled", "expired"
    ]
    status_received_at: datetime | None
    pending_event_count: int | None
    permission_granted: bool | None
    delivery_state: str | None
    last_acknowledged_event_id: str | None
    last_error_code: str | None


class SmsDeviceEnrollment(BaseModel):
    device: SmsDeviceRead
    api_key: str
