from dataclasses import dataclass

from src.modules.billing.sms.domain.models import SmsEventModel
from src.modules.billing.wallet.domain.models import TopupModel


@dataclass(frozen=True, slots=True)
class SmsSettlementFacts:
    topups: list[TopupModel]
    messages: list[SmsEventModel]


@dataclass(frozen=True, slots=True)
class SmsSettlementOwnerHint:
    """Untrusted initial facts used only to select the owning Customer lock."""

    topup_id: int
    customer_id: int
