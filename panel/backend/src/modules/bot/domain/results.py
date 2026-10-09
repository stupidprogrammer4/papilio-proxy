from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class BotHome:
    brand_title: str
    customer_id: int
    display_name: str
    balance_rial: int
    payment_instructions: str | None
    support_handle: str | None
    topup_options_rial: tuple[int, ...]


class BotDelivery(BaseModel):
    entitlement_kind: str
    subscription_id: int
    status: str
    auto_renew: bool
    feed_url: str | None
    portal_url: str | None
    can_rotate_link: bool


class BotSupportAccess(BaseModel):
    status: Literal["portal", "contact", "unavailable"]
    url: str | None
    expires_at: datetime | None
    support_handle: str | None
