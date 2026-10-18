from typing import Literal

from papilio.schemas.inputs import BaseDTO
from pydantic import Field

BotLocale = Literal["fa", "en", "ru", "zh"]


class BotIdentity(BaseDTO):
    telegram_id: int = Field(gt=0)
    display_name: str = Field(min_length=1, max_length=120)
    locale: BotLocale = "fa"


class BotTopup(BotIdentity):
    request_key: str | None = Field(default=None, min_length=8, max_length=64)
    destination_id: int | None = Field(default=None, gt=0)
    amount_rial: int = Field(gt=0)


class BotPurchase(BotIdentity):
    expected_price_rial: int | None = Field(default=None, ge=0)
    purchase_key: str = Field(min_length=8, max_length=128)
    plan_id: int = Field(gt=0)
    auto_renew: bool = False


class BotAutoRenew(BotIdentity):
    enabled: bool


class BotTrialClaim(BotIdentity):
    request_key: str = Field(min_length=8, max_length=64)
